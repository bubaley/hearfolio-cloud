<template>
  <div>
    <ol
      v-if="segments.length"
      class="flex flex-col"
      aria-label="Расшифровка"
    >
      <li
        v-for="(segment, index) in segments"
        :key="index"
        :ref="(el) => setRow(index, el)"
        class="group -mx-2 flex cursor-pointer gap-3 rounded-md px-2 py-1.5 transition-colors md:gap-4"
        :class="
          index === activeIndex ? 'bg-accent/70' : index === targetIndex ? 'bg-tag-yellow/60' : 'hover:bg-row-hover'
        "
        :aria-current="index === activeIndex ? 'true' : undefined"
        @click="onSegmentClick(segment, $event)"
      >
        <button
          type="button"
          class="h-6 w-12 shrink-0 rounded text-left text-xs leading-6 tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :class="index === activeIndex ? 'font-medium text-foreground' : 'text-muted-foreground'"
          :aria-label="`Воспроизвести с ${formatClock(segment.start_ms)}`"
          @click.stop="onSegmentClick(segment, $event)"
        >
          {{ formatClock(segment.start_ms) }}
        </button>
        <p
          class="min-w-0 flex-1 text-[0.9375rem] leading-6 break-words"
          :class="!segment.text.trim() && 'text-muted-foreground italic'"
        >
          <template v-if="terms.length && segment.text.trim()">
            <template
              v-for="(part, partIndex) in markTerms(segment.text.trim())"
              :key="partIndex"
            >
              <mark
                v-if="part.match"
                class="rounded-sm bg-tag-yellow px-0.5 text-tag-yellow-foreground"
                >{{ part.text }}</mark
              >
              <template v-else>{{ part.text }}</template>
            </template>
          </template>
          <template v-else>{{ segment.text.trim() || 'Тишина' }}</template>
        </p>
      </li>
    </ol>
    <div
      v-else-if="text"
      class="flex flex-col gap-3 text-[0.9375rem] leading-relaxed"
    >
      <p
        v-for="(paragraph, index) in text.split(/\n{2,}/)"
        :key="index"
      >
        {{ paragraph }}
      </p>
    </div>

    <Transition
      enter-from-class="translate-y-2 opacity-0"
      leave-to-class="translate-y-2 opacity-0"
      enter-active-class="transition"
      leave-active-class="transition"
    >
      <div
        v-if="showReturn"
        class="pointer-events-none sticky bottom-3 z-10 flex justify-center"
      >
        <AppButton
          size="sm"
          variant="secondary"
          class="pointer-events-auto shadow-overlay"
          :icon="LocateFixed"
          label="К текущему месту"
          @click="returnToActive"
        />
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { useEventListener } from '@vueuse/core'
import { LocateFixed } from '@lucide/vue'
import type { ComponentPublicInstance } from 'vue'
import type { TranscriptSegment } from '../../resources/recording'
import type { AudioPlayer } from '../../composables/useAudioPlayer'

const props = defineProps<{
  segments: TranscriptSegment[]
  text: string
  player: AudioPlayer
  /** The scrolling element the transcript lives in (auto-scroll target). */
  scroller: HTMLElement | null
  /** Search words from the list (`?q=`): highlighted; the first segment with them is shown and cued. */
  highlight?: string
  /** A moment to open at (`?t=` in ms): its segment is shown and cued. */
  focusMs?: number | null
}>()

const terms = computed(() =>
  (props.highlight ?? '')
    .toLocaleLowerCase('ru')
    .split(/\s+/)
    .map((term) => term.replace(/[^\p{L}\p{N}-]/gu, ''))
    .filter((term) => term.length > 1),
)
const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const markTerms = (text: string) => {
  const pattern = new RegExp(`(${terms.value.map(escapeRegExp).join('|')})`, 'giu')
  return text
    .split(pattern)
    .filter(Boolean)
    .map((part) => ({ text: part, match: terms.value.includes(part.toLocaleLowerCase('ru')) }))
}

// The segment a search hit or a `?t=` link points at: scrolled into view and cued in the player (no autoplay).
const targetIndex = ref(-1)
const findTarget = () => {
  const list = props.segments
  const at = props.focusMs
  if (at != null && Number.isFinite(at)) return list.findLastIndex((segment) => segment.start_ms <= at)
  if (!terms.value.length) return -1
  const lower = list.map((segment) => segment.text.toLocaleLowerCase('ru'))
  const all = lower.findIndex((text) => terms.value.every((term) => text.includes(term)))
  return all >= 0 ? all : lower.findIndex((text) => terms.value.some((term) => text.includes(term)))
}
let targeted = false
watch(
  () => props.segments.length,
  async (count) => {
    if (targeted || !count) return
    const index = findTarget()
    if (index < 0) return
    targeted = true
    targetIndex.value = index
    await nextTick()
    rows.get(index)?.scrollIntoView({ block: 'center' })
    void props.player.seek(props.segments[index]!.start_ms)
  },
  { immediate: true },
)

const rows = new Map<number, HTMLElement>()
const setRow = (index: number, el: Element | ComponentPublicInstance | null) => {
  if (el instanceof HTMLElement) rows.set(index, el)
  else rows.delete(index)
}

// The segment being played: the last one that started (binary search; segments are sorted by start).
const activeIndex = computed(() => {
  if (!props.player.started.value) return -1
  const time = props.player.currentMs.value
  const list = props.segments
  let low = 0
  let high = list.length - 1
  let found = -1
  while (low <= high) {
    const middle = (low + high) >> 1
    if (list[middle]!.start_ms <= time) {
      found = middle
      low = middle + 1
    } else high = middle - 1
  }
  return found
})

// Following the playback stops once the user scrolls on their own; it resumes when they scroll back to the playing
// segment, press «К текущему месту» or click a segment.
const userScrolling = ref(false)
const markUserScroll = () => {
  userScrolling.value = true
}
for (const name of ['wheel', 'touchmove'] as const)
  useEventListener(() => props.scroller, name, markUserScroll, { passive: true })
useEventListener(
  () => props.scroller,
  'keydown',
  (event: KeyboardEvent) => {
    if (['PageUp', 'PageDown', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) markUserScroll()
  },
)

const inView = (row: HTMLElement) => {
  const scroller = props.scroller
  if (!scroller) return true
  const box = scroller.getBoundingClientRect()
  const rect = row.getBoundingClientRect()
  return rect.top >= box.top + box.height * 0.1 && rect.bottom <= box.top + box.height * 0.8
}
const reveal = (index: number) => {
  const row = rows.get(index)
  if (row && !inView(row)) row.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

watch(activeIndex, (index) => {
  if (index < 0 || userScrolling.value || !props.player.playing.value) return
  reveal(index)
})

const offscreen = ref(false)
const checkOffscreen = () => {
  const row = rows.get(activeIndex.value)
  offscreen.value = Boolean(row) && !inView(row!)
  if (row && !offscreen.value) userScrolling.value = false
}
useEventListener(() => props.scroller, 'scroll', checkOffscreen, { passive: true })
watch(activeIndex, () => void nextTick(checkOffscreen))
const showReturn = computed(() => props.player.playing.value && userScrolling.value && offscreen.value)

const returnToActive = () => {
  userScrolling.value = false
  reveal(activeIndex.value)
}

const onSegmentClick = (segment: TranscriptSegment, event: MouseEvent) => {
  // Selecting text to copy must not jump the audio.
  if (window.getSelection()?.toString()) return
  event.preventDefault()
  userScrolling.value = false
  void props.player.seek(segment.start_ms, true)
}
</script>
