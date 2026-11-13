<template>
  <div
    class="flex items-center gap-2 rounded-xl border border-border bg-card/95 p-2 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-card/80 sm:gap-3 sm:px-3"
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
      @play="playing = true"
      @pause="playing = false"
      @ended="playing = false"
      @waiting="buffering = true"
      @playing="buffering = false"
      @error="onError"
    />
    <AppButton
      size="icon"
      class="size-11 shrink-0 rounded-full"
      :icon="playing ? Pause : Play"
      :loading="refreshing || (buffering && playing)"
      :aria-label="playing ? 'Пауза' : 'Слушать'"
      @click="toggle"
    />
    <AppButton
      variant="ghost"
      size="icon"
      text-variant="muted"
      class="hidden size-11 shrink-0 sm:inline-flex md:size-control-md"
      :icon="RotateCcw"
      aria-label="Назад на 15 секунд"
      title="−15 с"
      @click="skip(-15)"
    />
    <div class="flex min-w-0 flex-1 flex-col gap-1">
      <input
        :value="currentMs"
        type="range"
        min="0"
        :max="totalMs || 1"
        step="250"
        class="h-1.5 w-full cursor-pointer accent-primary"
        aria-label="Позиция воспроизведения"
        :aria-valuetext="`${formatClock(currentMs)} из ${formatClock(totalMs)}`"
        @input="onScrub"
      />
      <div class="flex justify-between text-xs text-muted-foreground tabular-nums">
        <span>{{ formatClock(currentMs) }}</span>
        <span>{{ formatClock(totalMs) }}</span>
      </div>
    </div>
    <AppButton
      variant="ghost"
      size="icon"
      text-variant="muted"
      class="hidden size-11 shrink-0 sm:inline-flex md:size-control-md"
      :icon="RotateCw"
      aria-label="Вперёд на 15 секунд"
      title="+15 с"
      @click="skip(15)"
    />
    <AppButton
      variant="ghost"
      size="sm"
      text-variant="muted"
      class="h-11 w-12 shrink-0 tabular-nums md:h-control-sm"
      :label="`${rate}×`"
      aria-label="Скорость воспроизведения"
      @click="cycleRate"
    />
  </div>
</template>

<script setup lang="ts">
import { Pause, Play, RotateCcw, RotateCw } from '@lucide/vue'

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
const loadedMs = ref(0)
const totalMs = computed(() => loadedMs.value || props.durationMs)
const RATES = [1, 1.25, 1.5, 2]
const rate = ref(1)

let resume: { atMs: number; play: boolean } | null = null

const expired = () => Date.parse(props.expiresAt) - Date.now() < 15_000

const renew = async (play: boolean) => {
  if (refreshing.value) return
  resume = { atMs: currentMs.value, play }
  refreshing.value = true
  try {
    await props.refresh()
  } finally {
    refreshing.value = false
  }
}

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
    if (resume.play) void element.play().catch(() => {})
    resume = null
  }
}

function onTime() {
  if (audio.value) currentMs.value = audio.value.currentTime * 1000
}

function onError() {
  // Most likely the presigned URL ran out; one refresh per failure keeps it from looping.
  if (!refreshing.value && expired()) void renew(playing.value || Boolean(resume?.play))
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
  await element.play().catch(() => {})
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
  if (element.paused) void element.play().catch(() => {})
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
