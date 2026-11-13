<template>
  <div
    class="flex flex-col gap-1 rounded-xl border border-border bg-card/95 p-2 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-card/80 sm:px-3"
    role="group"
    aria-label="Аудиоплеер"
  >
    <audio
      ref="audio"
      :src="src"
      preload="metadata"
      class="hidden"
      @loadedmetadata="onLoaded"
      @timeupdate="onTime"
      @play="onPlay"
      @pause="playing = false"
      @ended="playing = false"
      @waiting="buffering = true"
      @playing="buffering = false"
      @error="onError"
    />
    <div class="flex items-center gap-2 sm:gap-3">
      <div class="flex shrink-0 items-center gap-1">
        <AppButton
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="hidden size-11 shrink-0 sm:inline-flex md:size-control-md"
          :icon="RotateCcw"
          aria-label="Назад на 15 секунд"
          title="−15 с"
          :disabled="failed"
          @click="skip(-15)"
        />
        <AppButton
          size="icon"
          class="size-11 shrink-0 rounded-full"
          :icon="playing ? Pause : Play"
          :loading="refreshing || (buffering && playing)"
          :aria-label="playing ? 'Пауза' : 'Слушать'"
          :disabled="failed"
          @click="toggle"
        />
        <AppButton
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="hidden size-11 shrink-0 sm:inline-flex md:size-control-md"
          :icon="RotateCw"
          aria-label="Вперёд на 15 секунд"
          title="+15 с"
          :disabled="failed"
          @click="skip(15)"
        />
      </div>
      <div class="flex min-w-0 flex-1 flex-col gap-1">
        <input
          :value="currentMs"
          type="range"
          min="0"
          :max="totalMs || 1"
          step="250"
          class="h-1.5 w-full cursor-pointer accent-primary disabled:cursor-not-allowed"
          aria-label="Позиция воспроизведения"
          :aria-valuetext="`${formatClock(currentMs)} из ${formatClock(totalMs)}`"
          :disabled="failed"
          @input="onScrub"
        />
        <div class="flex justify-between text-xs text-muted-foreground tabular-nums">
          <span>{{ formatClock(currentMs) }}</span>
          <span>{{ formatClock(totalMs) }}</span>
        </div>
      </div>
      <AppButton
        variant="ghost"
        size="sm"
        text-variant="muted"
        class="h-11 w-12 shrink-0 tabular-nums md:h-control-sm"
        :label="`${String(rate).replace('.', ',')}×`"
        aria-label="Скорость воспроизведения"
        @click="cycleRate"
      />
    </div>
    <div
      v-if="failed"
      role="alert"
      class="flex items-center justify-center gap-2 pb-1 text-xs text-destructive"
    >
      <AppIcon
        :icon="CircleAlert"
        size="xs"
      />
      <span>Аудио недоступно</span>
      <AppTextButton
        label="Повторить"
        weight="medium"
        class="text-xs"
        @click="retry"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { CircleAlert, Pause, Play, RotateCcw, RotateCw } from '@lucide/vue'

/**
 * Player for a presigned audio URL. The URL expires (`expiresAt`): before playing a stale one, or when loading fails,
 * `refresh` fetches a fresh URL and playback continues from the same position.
 */
const props = defineProps<{
  src: string
  expiresAt: string
  durationMs: number
  refresh: () => Promise<unknown>
}>()
const currentMs = defineModel<number>('currentMs', { default: 0 })

const audio = ref<HTMLAudioElement>()
const playing = ref(false)
const buffering = ref(false)
const refreshing = ref(false)
// Loading or playing failed for another reason than an expired URL (or a fresh URL failed too).
const failed = ref(false)
const loadedMs = ref(0)
const totalMs = computed(() => loadedMs.value || props.durationMs)
const RATES = [1, 1.25, 1.5, 2]
const rate = ref(1)

let resume: { atMs: number; play: boolean } | null = null

const expired = () => Date.parse(props.expiresAt) - Date.now() < 15_000

// One automatic renewal per failure; a second error right after it is a real failure.
let renewed = false
const fail = () => {
  failed.value = true
  playing.value = false
  buffering.value = false
  resume = null
}

const renew = async (play: boolean) => {
  if (refreshing.value) return
  resume = { atMs: currentMs.value, play }
  refreshing.value = true
  renewed = true
  const before = props.src
  try {
    // A query refetch resolves with `{ error }` instead of throwing.
    const state = (await props.refresh()) as { error?: unknown } | undefined
    if (state?.error) throw state.error
  } catch {
    fail()
    return
  } finally {
    refreshing.value = false
  }
  // The same URL does not trigger the `src` watcher: load it again by hand (a second failure is then shown).
  await nextTick()
  if (props.src === before) audio.value?.load()
}

function onPlay() {
  playing.value = true
  failed.value = false
  renewed = false
}

/** «Повторить»: a fresh URL, then continue from the same position. */
async function retry() {
  failed.value = false
  renewed = false
  await renew(true)
}

const playElement = (element: HTMLAudioElement) =>
  element.play().catch((error: unknown) => {
    if (!(error instanceof DOMException && ['AbortError', 'NotAllowedError'].includes(error.name))) fail()
  })

// A new URL loads from scratch: restore the position (and playback) once its metadata is there.
watch(
  () => props.src,
  () => audio.value?.load(),
)

function onLoaded() {
  const element = audio.value
  if (!element) return
  if (Number.isFinite(element.duration)) loadedMs.value = element.duration * 1000
  element.playbackRate = rate.value
  if (resume) {
    element.currentTime = resume.atMs / 1000
    const shouldPlay = resume.play
    resume = null
    if (shouldPlay) void playElement(element)
  }
}

function onTime() {
  if (audio.value) currentMs.value = audio.value.currentTime * 1000
}

function onError() {
  if (refreshing.value || !props.src) return
  const wasPlaying = playing.value || Boolean(resume?.play)
  playing.value = false
  // Most likely the presigned URL ran out: renew once; a failure after that (or a fresh URL failing) is shown.
  if (!renewed) void renew(wasPlaying)
  else fail()
}

async function toggle() {
  const element = audio.value
  if (!element) return
  if (!element.paused) {
    element.pause()
    return
  }
  if (expired()) {
    await renew(true)
    return
  }
  await playElement(element)
}

function seek(ms: number) {
  const element = audio.value
  const target = Math.min(Math.max(0, ms), totalMs.value || ms)
  currentMs.value = target
  if (!element) return
  if (expired()) {
    resume = { atMs: target, play: true }
    void renew(true)
    return
  }
  element.currentTime = target / 1000
  if (element.paused) void playElement(element)
}

function skip(seconds: number) {
  seek(currentMs.value + seconds * 1000)
}

function onScrub(event: Event) {
  const ms = Number((event.target as HTMLInputElement).value)
  currentMs.value = ms
  if (audio.value && !expired()) audio.value.currentTime = ms / 1000
}

function cycleRate() {
  rate.value = RATES[(RATES.indexOf(rate.value) + 1) % RATES.length]!
  if (audio.value) audio.value.playbackRate = rate.value
}

defineExpose({ seek })
</script>
