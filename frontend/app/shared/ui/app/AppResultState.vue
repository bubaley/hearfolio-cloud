<template>
  <div
    class="flex flex-col items-center gap-3 py-2 text-center"
    :role="tone === 'destructive' || tone === 'warning' ? 'alert' : 'status'"
  >
    <span
      v-if="icon"
      class="flex size-11 items-center justify-center rounded-full"
      :class="toneVariants({ tone, appearance: 'soft' })"
    >
      <AppIcon
        :icon="icon"
        size="md"
      />
    </span>
    <div class="flex flex-col gap-1">
      <h1 class="text-lg font-semibold text-balance">{{ title }}</h1>
      <p
        v-if="description || $slots.default"
        class="text-sm text-balance text-muted-foreground"
      >
        <slot>{{ description }}</slot>
      </p>
    </div>
    <div
      v-if="$slots.actions"
      class="mt-2 flex w-full flex-col gap-2"
    >
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Component } from 'vue'
import { toneVariants, type Tone } from './tone'

/** A centered outcome or empty state: icon in a tinted circle, title, text and full-width actions. */
withDefaults(defineProps<{ title: string; description?: string; icon?: Component; tone?: Tone }>(), {
  tone: 'muted',
})
</script>
