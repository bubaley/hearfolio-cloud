<template>
  <!-- Left-aligned like the content of the tab it stands in: icon, title, text, then an optional action. -->
  <div
    class="flex flex-col items-start gap-4 py-2"
    role="status"
  >
    <span
      class="flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground"
      aria-hidden="true"
    >
      <AppIcon
        :icon="icon"
        size="md"
      />
    </span>
    <div class="flex flex-col gap-1">
      <h3 class="text-lg font-semibold">{{ title }}</h3>
      <p
        v-if="description"
        class="max-w-md text-sm text-muted-foreground"
      >
        {{ description }}
      </p>
    </div>
    <slot />
  </div>
</template>

<script setup lang="ts">
import type { Component } from 'vue'

/** The empty state of a recording tab (transcript, summaries, history). */
defineProps<{ icon: Component; title: string; description?: string }>()
</script>
