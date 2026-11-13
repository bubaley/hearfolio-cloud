<template>
  <span
    class="inline-flex h-5 max-w-full min-w-0 items-center rounded-sm px-1.5 text-xs leading-none"
    :class="tagChipClass(color)"
  >
    <span class="truncate">{{ name }}</span>
  </span>
</template>

<script setup lang="ts">
import type { TagColor } from '../resources/tag'
import { tagChipClass } from '../composables/tagColors'

defineProps<{ name: string; color: TagColor | null | undefined }>()
</script>
