<template>
  <span
    v-if="tags.length"
    ref="root"
    class="relative flex min-w-0 flex-wrap content-start items-center gap-1 overflow-hidden"
    :style="{ maxHeight: `${lines * 1.25 + (lines - 1) * 0.25}rem` }"
  >
    <TagChip
      v-for="tag in tags"
      :key="tag.id"
      data-tag-chip
      :name="tag.name"
      :color="tag.color"
    />
    <AppTooltip :disabled="!hidden.length">
      <template #trigger>
        <span
          ref="counter"
          class="relative z-1 h-5 shrink-0 items-center px-0.5 text-xs text-muted-foreground tabular-nums"
          :class="hidden.length ? 'inline-flex' : 'hidden'"
          :aria-label="hidden.length ? `Ещё теги: ${hiddenNames}` : undefined"
          >+{{ hidden.length }}</span
        >
      </template>
      {{ hiddenNames }}
    </AppTooltip>
  </span>
</template>

<script setup lang="ts">
import { useResizeObserver } from '@vueuse/core'
import type { TagColor } from '../resources/tag'
import TagChip from './TagChip.vue'

/**
 * Tags of a dense row: whole chips wrapped onto at most `lines` lines; what does not fit collapses into «+N» (its
 * tooltip names the rest). Chips are measured in the DOM, so the real font and the slot width decide, not a guess;
 * the first chip always shows (a very long name truncates inside the slot).
 */
const props = withDefaults(
  defineProps<{ tags: { id: string; name: string; color?: TagColor | null }[]; lines?: number }>(),
  { lines: 2 },
)

const root = ref<HTMLElement>()
const counter = ref<HTMLElement>()
const visible = ref(props.tags.length)

const hidden = computed(() => props.tags.slice(visible.value))
const hiddenNames = computed(() => hidden.value.map((tag) => tag.name).join(', '))

// Works on the elements directly (not through reactive state) so one pass settles without re-render flicker.
const measure = () => {
  const box = root.value
  const more = counter.value
  if (!box || !more) return
  const chips = [...box.querySelectorAll<HTMLElement>('[data-tag-chip]')]
  for (const chip of chips) chip.style.display = ''
  more.style.display = 'none'

  const tops: number[] = []
  let fit = 0
  for (const chip of chips) {
    if (!tops.includes(chip.offsetTop)) tops.push(chip.offsetTop)
    if (tops.length > props.lines) break
    fit += 1
  }
  if (fit < chips.length) {
    const lastLine = tops[Math.min(props.lines, tops.length) - 1] ?? 0
    more.style.display = 'inline-flex'
    const place = () => {
      chips.forEach((chip, index) => (chip.style.display = index < fit ? '' : 'none'))
      more.textContent = `+${chips.length - fit}`
    }
    place()
    // The counter must sit on an allowed line; give it room by dropping chips from the end.
    while (fit > 1 && more.offsetTop > lastLine) {
      fit -= 1
      place()
    }
  }
  more.style.display = ''
  visible.value = fit
}

useResizeObserver(root, () => measure())
watch(
  () => props.tags.map((tag) => `${tag.id}:${tag.name}`).join('|'),
  () => nextTick(measure),
)
onMounted(measure)
</script>
