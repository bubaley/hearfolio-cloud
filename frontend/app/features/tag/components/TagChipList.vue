<template>
  <span
    v-if="tags.length"
    class="flex min-w-0 items-center gap-1 overflow-hidden"
    :title="hidden ? tags.map((tag) => tag.name).join(', ') : undefined"
  >
    <TagChip
      v-for="tag in fitted"
      :key="tag.id"
      :name="tag.name"
      :color="tag.color"
      class="min-w-0"
      :class="fitted.length > 1 && 'shrink-0'"
    />
    <span
      v-if="hidden"
      class="shrink-0 text-xs text-muted-foreground tabular-nums"
      >+{{ hidden }}</span
    >
  </span>
</template>

<script setup lang="ts">
import type { TagColor } from '../resources/tag'
import { fitTagChips } from '../composables/tagColors'
import TagChip from './TagChip.vue'

/**
 * Tags of a dense row: whole chips only, as many as fit `budget` (rem, the width of the slot), then «+N».
 * The parent gives the slot a fixed width, so the column never jumps between rows.
 */
const props = defineProps<{ tags: { id: string; name: string; color?: TagColor | null }[]; budget: number }>()

const fitted = computed(() => fitTagChips(props.tags, props.budget))
const hidden = computed(() => props.tags.length - fitted.value.length)
</script>
