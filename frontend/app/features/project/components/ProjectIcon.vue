<template>
  <span
    class="inline-flex shrink-0 items-center justify-center leading-none"
    :class="size === 'lg' ? 'size-14 text-5xl' : 'size-5 text-base'"
    aria-hidden="true"
  >
    <template v-if="emoji">{{ emoji }}</template>
    <AppIcon
      v-else
      :icon="Folder"
      :size="size === 'lg' ? 44 : 'sm'"
      class="text-muted-foreground"
    />
  </span>
</template>

<script setup lang="ts">
import { Folder } from '@lucide/vue'

withDefaults(defineProps<{ emoji?: string | null; size?: 'md' | 'lg' }>(), { size: 'md' })
</script>
