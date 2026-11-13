import type { UploadPartSchema, UploadPlanSchema, UploadedPartSchema } from '~/shared/api/generated'

// Browser side of the upload API (docs/product.md, «API contract for the apps»): a single presigned PUT or S3
// multipart parts straight to the bucket, then `upload/complete`.

const MIME_BY_EXTENSION: Record<string, string> = {
  m4a: 'audio/mp4',
  mp4: 'audio/mp4',
  aac: 'audio/aac',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  ogg: 'audio/ogg',
  oga: 'audio/ogg',
  opus: 'audio/ogg',
  webm: 'audio/webm',
  flac: 'audio/flac',
  amr: 'audio/amr',
  '3gp': 'audio/3gpp',
}

export const AUDIO_ACCEPT = ['audio/*', 'video/*', ...Object.keys(MIME_BY_EXTENSION).map((ext) => `.${ext}`)].join(',')
export const UPLOAD_MAX_BYTES = 10 * 1024 ** 3

const extension = (name: string) => name.split('.').pop()?.toLowerCase() ?? ''

const isMediaType = (type: string) => type.startsWith('audio/') || type.startsWith('video/')

/** The server accepts `audio/*` and `video/*` (a recorded call is often an .mp4 or .webm video). */
export const audioMime = (file: File) =>
  isMediaType(file.type) ? file.type : (MIME_BY_EXTENSION[extension(file.name)] ?? 'audio/mpeg')

export const isAudioFile = (file: File) => isMediaType(file.type) || extension(file.name) in MIME_BY_EXTENSION

export const fileTitle = (name: string) => name.replace(/\.[^.]+$/, '').trim()

/** Duration in ms from the browser's own decoder; 0 when it cannot tell (the server fills it in later). */
export const probeDuration = (file: File, timeoutMs = 8000): Promise<number> =>
  new Promise((resolve) => {
    const audio = document.createElement('audio')
    const url = URL.createObjectURL(file)
    let settled = false
    const finish = (ms: number) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      audio.removeAttribute('src')
      audio.load()
      URL.revokeObjectURL(url)
      resolve(Number.isFinite(ms) && ms > 0 ? Math.round(ms) : 0)
    }
    const timer = setTimeout(() => finish(0), timeoutMs)
    audio.preload = 'metadata'
    audio.addEventListener('error', () => finish(0))
    audio.addEventListener('loadedmetadata', () => {
      // WebM/Opus from MediaRecorder reports Infinity until the decoder has seen the end.
      if (audio.duration === Infinity) {
        audio.addEventListener('durationchange', () => finish(audio.duration * 1000), { once: true })
        audio.currentTime = 1e7
        return
      }
      finish(audio.duration * 1000)
    })
    audio.src = url
  })

/** A failure with a Russian, user-facing message. */
export class UploadError extends Error {}

export class UploadHttpError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`)
  }
}

/** PUT with progress (fetch has no upload progress). Resolves to the ETag when S3 exposes it through CORS. */
export const putBlob = (
  url: string,
  body: Blob,
  options: { headers?: Record<string, string>; signal?: AbortSignal; onProgress?: (loaded: number) => void },
) =>
  new Promise<string | null>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    // The browser sends the exact `Content-Length` of the Blob itself (the presigned URL signs it); it refuses to
    // let scripts set it or `Host`.
    for (const [name, value] of Object.entries(options.headers ?? {}))
      if (!['content-length', 'host'].includes(name.toLowerCase())) xhr.setRequestHeader(name, value)
    xhr.upload.onprogress = (event) => options.onProgress?.(event.loaded)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.getResponseHeader('ETag'))
      else reject(new UploadHttpError(xhr.status))
    }
    xhr.onerror = () => reject(new UploadHttpError(0))
    xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'))
    if (options.signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    options.signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(body)
  })

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })

export const isAbort = (error: unknown) => error instanceof DOMException && error.name === 'AbortError'

/** Up to `attempts` tries with exponential backoff; aborts are never retried. */
export const withRetries = async <T>(
  task: (attempt: number) => Promise<T>,
  {
    attempts = 4,
    signal,
    retryIf = () => true,
  }: { attempts?: number; signal?: AbortSignal; retryIf?: (error: unknown) => boolean } = {},
) => {
  for (let attempt = 1; ; attempt++) {
    try {
      return await task(attempt)
    } catch (error) {
      if (isAbort(error) || attempt >= attempts || !retryIf(error)) throw error
      await wait(1000 * 2 ** (attempt - 1), signal)
    }
  }
}

type MultipartOptions = {
  file: File
  plan: UploadPlanSchema
  signal: AbortSignal
  onProgress: (loaded: number) => void
  /** Fresh presigned URLs (`POST /recordings/{id}/upload/parts`) when the old ones expired. */
  refreshParts: (partNumbers: number[]) => Promise<UploadPartSchema[]>
  concurrency?: number
  /** Upload only these part numbers (S3 reported them missing). */
  only?: number[]
}

/** Uploads every part (three at a time, each with retries); returns the ETags, or null when S3 hides them. */
export const uploadMultipart = async ({
  file,
  plan,
  signal,
  onProgress,
  refreshParts,
  concurrency = 3,
  only,
}: MultipartOptions): Promise<UploadedPartSchema[] | null> => {
  const partSize = plan.part_size ?? 0
  const urls = new Map((plan.parts ?? []).map((part) => [part.part_number, part.url]))
  const count = plan.parts_count ?? urls.size
  if (!partSize || !count) throw new UploadError('Сервер вернул пустой план загрузки')
  const loaded = new Map<number, number>()
  const report = () => onProgress([...loaded.values()].reduce((sum, value) => sum + value, 0))
  const etags = new Map<number, string | null>()
  const queue = only ? [...only] : Array.from({ length: count }, (_, index) => index + 1)

  const uploadPart = async (partNumber: number) => {
    const blob = file.slice((partNumber - 1) * partSize, partNumber * partSize)
    const etag = await withRetries(
      async () => {
        let url = urls.get(partNumber)
        if (!url) {
          const [fresh] = await refreshParts([partNumber])
          url = fresh?.url
          if (!url) throw new UploadError('Нет ссылки для загрузки части')
          urls.set(partNumber, url)
        }
        try {
          return await putBlob(url, blob, {
            signal,
            onProgress: (value) => {
              loaded.set(partNumber, value)
              report()
            },
          })
        } catch (error) {
          loaded.set(partNumber, 0)
          report()
          // An expired presigned URL answers 403: drop it so the next attempt asks for a fresh one.
          if (error instanceof UploadHttpError && error.status === 403) urls.delete(partNumber)
          throw error
        }
      },
      { signal },
    )
    loaded.set(partNumber, blob.size)
    report()
    etags.set(partNumber, etag)
  }

  const worker = async () => {
    for (let next = queue.shift(); next !== undefined; next = queue.shift()) await uploadPart(next)
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, count) }, worker))

  const parts = [...etags.entries()].sort(([a], [b]) => a - b)
  if (parts.some(([, etag]) => !etag)) return null
  return parts.map(([part_number, etag]) => ({ part_number, etag: etag! }))
}
