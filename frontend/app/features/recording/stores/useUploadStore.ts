import { useQueryCache } from '@pinia/colada'
import { defineStore } from 'pinia'
import { markRaw } from 'vue'
import {
  recordingsCreate,
  recordingsDestroy,
  recordingsUploadComplete,
  recordingsUploadParts,
  type RecordingVisibility,
  type UploadedPartSchema,
} from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { useApiClient } from '~/shared/api/useResource'
import { apiErrorReason } from '~/features/organization/composables/organizationErrors'
import { recordingErrorMessage, recordingKeys } from '../composables/useRecordingMutations'
import {
  audioMime,
  fileTitle,
  isAbort,
  probeDuration,
  putBlob,
  uploadMultipart,
  UploadError,
  UploadHttpError,
  withRetries,
} from '../utils/audioUpload'

export type UploadState = 'queued' | 'preparing' | 'uploading' | 'completing' | 'done' | 'failed'

export type UploadItem = {
  key: string
  file: File
  name: string
  size: number
  loaded: number
  state: UploadState
  error: string | null
  /** Idempotency key: a retry re-POSTs it and gets the same recording with a fresh plan. */
  clientId: string
  recordingId: string | null
  organizationId: string
  projectId: string | null
  visibility: RecordingVisibility
  durationMs: number | null
  controller: AbortController | null
}

export type UploadOptions = { projectId: string | null; visibility: RecordingVisibility }

// `details.reason` of upload rejections (docs/product.md → Upload details). «Повторить» re-POSTs the same
// `client_id`, which returns the recording with a fresh upload plan.
const UPLOAD_REASONS: Record<string, string> = {
  upload_incomplete: 'Хранилище ещё не видит файл — нажмите «Повторить»',
  upload_parts_missing: 'Часть файла не дошла до хранилища — нажмите «Повторить»',
  upload_size_mismatch: 'Файл дошёл до хранилища не целиком — нажмите «Повторить», он загрузится заново',
  upload_failed: 'Загрузка прервалась — нажмите «Повторить», чтобы начать заново',
  upload_expired: 'Загрузка устарела — нажмите «Повторить», чтобы начать заново',
  storage_unavailable: 'Хранилище файлов сейчас недоступно — повторите позже',
  unsupported_media_type: 'Этот формат не поддерживается: загрузите аудио или видео',
}

const S3_ERROR = 'Хранилище не приняло файл. Проверьте подключение и повторите'
// Status 0: the request never got an answer — offline, or the bucket does not allow uploads from this site (CORS).
const S3_UNREACHABLE =
  'Нет связи с хранилищем файлов. Проверьте интернет; если ошибка повторяется, администратору нужно разрешить загрузку из браузера в настройках хранилища (CORS)'

/**
 * Browser uploads (the «Загрузить» button and drag & drop): one file at a time, parts three at a time. Lives for the
 * whole tab so navigating away keeps uploading; the tray shows progress, cancel and retry.
 */
export const useUploadStore = defineStore('recording-uploads', () => {
  const items = ref<UploadItem[]>([])
  const client = useApiClient()
  const queryCache = useQueryCache()
  const setupStore = useSetupStore()
  let running = false

  const active = computed(() => items.value.filter((item) => !['done', 'failed'].includes(item.state)))

  const assertOrganization = (item: UploadItem) => {
    if (setupStore.state.organization?.id !== item.organizationId)
      throw new UploadError('Вы переключили организацию — вернитесь в неё, чтобы продолжить загрузку')
  }

  const upload = async (item: UploadItem) => {
    const controller = new AbortController()
    item.controller = markRaw(controller)
    const { signal } = controller
    item.error = null
    item.loaded = 0
    try {
      item.state = 'preparing'
      item.durationMs ??= await probeDuration(item.file)
      assertOrganization(item)
      const { data: created } = await recordingsCreate({
        client,
        throwOnError: true,
        signal,
        body: {
          client_id: item.clientId,
          // The file name until the AI title replaces it (`auto`); a rename by the user wins over both.
          title: item.name,
          title_source: 'auto',
          recorded_at: new Date(item.file.lastModified || Date.now()).toISOString(),
          duration_ms: item.durationMs ?? 0,
          source: 'web',
          original_filename: item.file.name,
          audio_mime: audioMime(item.file),
          audio_size: item.file.size,
          project_id: item.projectId,
          visibility: item.visibility,
        },
      })
      item.recordingId = created.recording.id
      void queryCache.invalidateQueries({ key: recordingKeys.lists })
      const plan = created.upload
      item.state = 'uploading'
      let parts: UploadedPartSchema[] | null = null
      if (plan?.method === 'single' && plan.url) {
        await withRetries(
          () =>
            putBlob(plan.url!, item.file, {
              headers: plan.headers,
              signal,
              onProgress: (loaded) => {
                item.loaded = loaded
              },
            }),
          { signal },
        )
      } else if (plan?.method === 'multipart') {
        const recordingId = item.recordingId
        parts = await uploadMultipart({
          file: item.file,
          plan,
          signal,
          onProgress: (loaded) => {
            item.loaded = loaded
          },
          refreshParts: async (part_numbers) => {
            assertOrganization(item)
            const { data } = await recordingsUploadParts({
              client,
              throwOnError: true,
              path: { item_id: recordingId },
              body: { part_numbers },
            })
            return data.parts ?? []
          },
        })
      }
      item.loaded = item.size
      item.state = 'completing'
      assertOrganization(item)
      const complete = () =>
        withRetries(
          () =>
            recordingsUploadComplete({
              client,
              throwOnError: true,
              signal,
              path: { item_id: created.recording.id },
              body: parts ? { parts } : {},
            }),
          { attempts: 3, signal, retryIf: (error) => !isApiError(error) || error.status >= 500 },
        )
      try {
        await complete()
      } catch (error) {
        // S3 lacks some parts: upload just those once more (fresh URLs) and complete again.
        const missing = isApiError(error) ? error.details?.missing_parts : undefined
        if (apiErrorReason(error) !== 'upload_parts_missing' || !Array.isArray(missing) || !plan) throw error
        await uploadMultipart({
          file: item.file,
          plan: { ...plan, parts: [] },
          only: missing as number[],
          signal,
          onProgress: () => undefined,
          refreshParts: (part_numbers) =>
            recordingsUploadParts({
              client,
              throwOnError: true,
              path: { item_id: created.recording.id },
              body: { part_numbers },
            }).then(({ data }) => data.parts ?? []),
        })
        // The ETags of the earlier parts are not all known now: the server lists the uploaded parts itself.
        parts = null
        await complete()
      }
      item.state = 'done'
      void queryCache.invalidateQueries({ key: recordingKeys.lists })
    } catch (error) {
      if (isAbort(error)) return
      item.state = 'failed'
      item.error =
        error instanceof UploadHttpError
          ? error.status
            ? S3_ERROR
            : S3_UNREACHABLE
          : error instanceof UploadError
            ? error.message
            : (UPLOAD_REASONS[apiErrorReason(error) ?? ''] ?? recordingErrorMessage(error, 'Не удалось загрузить файл'))
    } finally {
      item.controller = null
    }
  }

  const pump = async () => {
    if (running) return
    running = true
    try {
      for (let next = items.value.find((item) => item.state === 'queued'); next;) {
        await upload(next)
        next = items.value.find((item) => item.state === 'queued')
      }
    } finally {
      running = false
    }
  }

  const add = (files: File[], options: UploadOptions) => {
    const organizationId = setupStore.state.organization?.id
    if (!organizationId) return
    for (const file of files) {
      items.value.push({
        key: crypto.randomUUID(),
        file: markRaw(file),
        name: fileTitle(file.name) || file.name,
        size: file.size,
        loaded: 0,
        state: 'queued',
        error: null,
        clientId: crypto.randomUUID(),
        recordingId: null,
        organizationId,
        projectId: options.projectId,
        visibility: options.visibility,
        durationMs: null,
        controller: null,
      })
    }
    void pump()
  }

  const retry = (key: string) => {
    const item = items.value.find((entry) => entry.key === key)
    if (!item || item.state !== 'failed') return
    item.state = 'queued'
    void pump()
  }

  /** Stops the upload and deletes the half-created recording, so it does not hang in «Загружается». */
  const cancel = async (key: string) => {
    const item = items.value.find((entry) => entry.key === key)
    if (!item) return
    item.controller?.abort()
    items.value = items.value.filter((entry) => entry.key !== key)
    if (item.recordingId && item.state !== 'done') {
      await recordingsDestroy({ client, path: { item_id: item.recordingId } }).catch(() => undefined)
      void queryCache.invalidateQueries({ key: recordingKeys.lists })
    }
  }

  const dismiss = (key: string) => {
    items.value = items.value.filter((entry) => entry.key !== key)
  }

  const clearFinished = () => {
    items.value = items.value.filter((item) => item.state !== 'done')
  }

  // Uploads belong to the organization they started in; leaving it must not file the rest elsewhere.
  watch(
    () => setupStore.state.organization?.id,
    (id) => {
      for (const item of items.value) {
        if (item.organizationId !== id && item.state !== 'done' && item.state !== 'failed') {
          item.controller?.abort()
          item.state = 'failed'
          item.error = 'Загрузка остановлена: вы переключили организацию'
        }
      }
    },
  )

  return { items, active, add, retry, cancel, dismiss, clearFinished }
})
