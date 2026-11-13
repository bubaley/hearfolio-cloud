import { useEventListener } from '@vueuse/core'
import type { AudioUrlSchema } from '~/shared/api/generated'

export const PLAYBACK_RATES = [1, 1.25, 1.5, 2] as const

type AudioSource = {
  /** Current presigned URL, if loaded. */
  url: () => AudioUrlSchema | null | undefined
  /** Fresh URL (the presigned one lives a few minutes). */
  refresh: () => Promise<AudioUrlSchema | null | undefined>
  title: () => string
  /** Known length before the browser reads the file. */
  durationMs: () => number
}

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A'].includes(target.tagName) ||
    Boolean(target.closest('[role="dialog"],[role="menu"],[role="listbox"],[role="slider"]')))

/**
 * One `<audio>` for the recording page: play/pause, seek, ±15 s, speed, space to toggle, ←/→ for ±5 s and lock-screen
 * controls.
 * The presigned URL is fetched again when it expired or the browser reports a load error, keeping the position.
 */
export const useAudioPlayer = (source: AudioSource) => {
  const audio = import.meta.client ? new Audio() : null
  if (audio) audio.preload = 'metadata'

  const playing = ref(false)
  const loading = ref(false)
  const failed = ref(false)
  const currentMs = ref(0)
  const loadedDurationMs = ref(0)
  const rate = ref<number>(1)
  const started = ref(false)
  let currentUrl: string | null = null
  // Seconds to jump to once the browser has read the file's metadata (setting currentTime earlier is ignored).
  let pendingSeek: number | null = null
  const setTime = (seconds: number) => {
    if (!audio) return
    if (audio.readyState >= 1) audio.currentTime = seconds
    else pendingSeek = seconds
  }

  const durationMs = computed(() => loadedDurationMs.value || source.durationMs())

  const expired = (value: AudioUrlSchema) => Date.parse(value.expires_at) - Date.now() < 30_000

  const ensureSource = async (forceRefresh = false) => {
    if (!audio) return false
    let value = source.url()
    if (forceRefresh || !value || expired(value)) value = await source.refresh()
    if (!value) return false
    if (value.url !== currentUrl) {
      const position = pendingSeek ?? audio.currentTime
      currentUrl = value.url
      audio.src = value.url
      audio.playbackRate = rate.value
      if (position) pendingSeek = position
    }
    return true
  }

  const play = async () => {
    if (!audio) return
    failed.value = false
    loading.value = true
    try {
      if (!(await ensureSource())) throw new Error('no audio')
      started.value = true
      await audio.play()
    } catch (error) {
      if (!(error instanceof DOMException && ['AbortError', 'NotAllowedError'].includes(error.name))) {
        failed.value = true
        playing.value = false
      }
    } finally {
      loading.value = false
    }
  }
  const pause = () => audio?.pause()
  const toggle = () => (playing.value ? pause() : void play())
  /** «Повторить» after a failure: a fresh URL, then play from the same position. */
  const reload = async () => {
    if (!audio) return
    failed.value = false
    currentUrl = null
    if (currentMs.value) pendingSeek = currentMs.value / 1000
    try {
      if (!(await ensureSource(true))) throw new Error('no audio')
    } catch {
      failed.value = true
      return
    }
    await play()
  }

  const seek = async (ms: number, autoplay = false) => {
    if (!audio) return
    const target = Math.max(0, Math.min(ms, durationMs.value || ms))
    currentMs.value = target
    if (!currentUrl && !(await ensureSource())) return
    started.value = true
    setTime(target / 1000)
    if (autoplay && !playing.value) await play()
  }
  const skip = (deltaMs: number) => seek(currentMs.value + deltaMs)

  const setRate = (value: number) => {
    rate.value = value
    if (audio) audio.playbackRate = value
  }
  const cycleRate = () => {
    const index = PLAYBACK_RATES.indexOf(rate.value as (typeof PLAYBACK_RATES)[number])
    setRate(PLAYBACK_RATES[(index + 1) % PLAYBACK_RATES.length]!)
  }

  if (audio) {
    useEventListener(audio, 'play', () => {
      playing.value = true
    })
    useEventListener(audio, 'pause', () => {
      playing.value = false
    })
    useEventListener(audio, 'ended', () => {
      playing.value = false
    })
    useEventListener(audio, 'waiting', () => {
      loading.value = true
    })
    useEventListener(audio, 'playing', () => {
      loading.value = false
    })
    useEventListener(audio, 'timeupdate', () => {
      currentMs.value = audio.currentTime * 1000
    })
    useEventListener(audio, 'loadedmetadata', () => {
      if (Number.isFinite(audio.duration)) loadedDurationMs.value = audio.duration * 1000
      audio.playbackRate = rate.value
      if (pendingSeek !== null) {
        audio.currentTime = pendingSeek
        pendingSeek = null
      }
    })
    // An expired presigned URL fails as a media error: fetch a new one once and continue where it stopped.
    let retried = false
    useEventListener(audio, 'error', async () => {
      if (!currentUrl) return
      const wasPlaying = playing.value
      // The element stops on a media error without a `pause` event: never leave the pause icon on a dead player.
      playing.value = false
      if (retried) {
        failed.value = true
        loading.value = false
        return
      }
      retried = true
      try {
        if (!(await ensureSource(true))) throw new Error('no audio')
        if (wasPlaying) await play()
      } catch {
        failed.value = true
        loading.value = false
      }
    })
    useEventListener(audio, 'canplay', () => {
      retried = false
    })

    // Space toggles playback, ←/→ jump 5 s, unless the user is typing or on a control that uses the key itself.
    useEventListener(window, 'keydown', (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return
      if (isTyping(event.target)) return
      if (event.code === 'Space') {
        event.preventDefault()
        if (!event.repeat) toggle()
      } else if ((event.key === 'ArrowLeft' || event.key === 'ArrowRight') && started.value) {
        event.preventDefault()
        void skip(event.key === 'ArrowLeft' ? -5_000 : 5_000)
      }
    })

    if ('mediaSession' in navigator) {
      watch(
        () => [started.value, source.title()] as const,
        ([isStarted, title]) => {
          if (!isStarted) return
          navigator.mediaSession.metadata = new MediaMetadata({ title, artist: 'Hearfolio' })
          navigator.mediaSession.setActionHandler('play', () => void play())
          navigator.mediaSession.setActionHandler('pause', pause)
          navigator.mediaSession.setActionHandler('seekbackward', () => void skip(-15_000))
          navigator.mediaSession.setActionHandler('seekforward', () => void skip(15_000))
        },
      )
    }

    onBeforeUnmount(() => {
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
      if ('mediaSession' in navigator) navigator.mediaSession.metadata = null
    })
  }

  return {
    playing,
    loading,
    failed,
    started,
    currentMs,
    durationMs,
    rate,
    play,
    pause,
    toggle,
    reload,
    seek,
    skip,
    setRate,
    cycleRate,
  }
}

export type AudioPlayer = ReturnType<typeof useAudioPlayer>
