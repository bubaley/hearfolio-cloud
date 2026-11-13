<template>
  <ol
    v-if="visibleSegments.length"
    class="-mx-2 flex flex-col"
  >
    <li
      v-for="(segment, index) in visibleSegments"
      :key="index"
    >
      <component
        :is="seekable ? 'button' : 'div'"
        :type="seekable ? 'button' : undefined"
        class="group flex w-full gap-3 rounded-md px-2 py-1.5 text-left transition-colors outline-none sm:gap-4"
        :class="[
          seekable && 'hover:bg-row-hover focus-visible:ring-2 focus-visible:ring-ring',
          index === activeIndex && 'bg-accent/70 hover:bg-accent/70',
        ]"
        :aria-current="index === activeIndex ? 'true' : undefined"
        :aria-label="seekable ? `Перейти к ${formatClock(segment.start_ms)}` : undefined"
        @click="seekable && emit('seek', segment.start_ms)"
      >
        <span
          class="w-12 shrink-0 pt-0.5 text-xs text-muted-foreground tabular-nums"
          :class="seekable && 'group-hover:text-primary'"
          >{{ formatClock(segment.start_ms) }}</span
        >
        <span class="min-w-0 flex-1 text-[0.95rem] leading-relaxed break-words">{{ segment.text }}</span>
      </component>
    </li>
  </ol>
  <div
    v-else
    class="flex flex-col gap-3 text-[0.95rem] leading-relaxed break-words"
  >
    <p
      v-for="(paragraph, index) in paragraphs"
      :key="index"
    >
      {{ paragraph }}
    </p>
  </div>
</template>

<script setup lang="ts">
import type { TranscriptSegmentSchema } from '~/shared/api/generated'
import { formatClock } from '../composables/usePublicShare'

/** Transcript by segments with timestamps; with audio a click seeks and the playing segment is highlighted. */
const props = defineProps<{
  segments: TranscriptSegmentSchema[]
  text: string
  currentMs?: number
  seekable?: boolean
}>()
const emit = defineEmits<{ seek: [ms: number] }>()

// Silent chunks become empty segments: hide them.
const visibleSegments = computed(() => props.segments.filter((segment) => segment.text.trim()))
const activeIndex = computed(() => {
  if (!props.seekable || props.currentMs === undefined || props.currentMs <= 0) return -1
  return visibleSegments.value.findIndex(
    (segment) => props.currentMs! >= segment.start_ms && props.currentMs! < segment.end_ms,
  )
})
const paragraphs = computed(() =>
  props.text
    .split(/\n{2,}|\n/)
    .map((line) => line.trim())
    .filter(Boolean),
)
</script>
