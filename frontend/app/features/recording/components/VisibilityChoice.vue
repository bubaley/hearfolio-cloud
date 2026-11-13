<template>
  <div
    role="radiogroup"
    aria-label="Доступ"
    class="grid grid-cols-2 gap-2"
  >
    <button
      v-for="option in OPTIONS"
      :key="option.value"
      type="button"
      role="radio"
      :aria-checked="model === option.value"
      class="flex min-h-11 items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :class="model === option.value ? 'border-foreground/60 bg-accent/60' : 'border-border hover:bg-field-hover'"
      @click="model = option.value"
    >
      <AppIcon
        :icon="option.icon"
        size="sm"
        class="mt-0.5 shrink-0"
      />
      <span class="flex min-w-0 flex-col gap-0.5">
        <span class="text-sm font-medium">{{ option.label }}</span>
        <span class="text-xs text-muted-foreground">{{ option.hint }}</span>
      </span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { Lock, Users } from '@lucide/vue'
import type { RecordingVisibility } from '~/shared/api/generated'

const model = defineModel<RecordingVisibility>({ required: true })

const OPTIONS = [
  { value: 'organization' as const, label: 'Общая', hint: 'Видят участники организации или проекта', icon: Users },
  { value: 'personal' as const, label: 'Личная', hint: 'Видите только вы', icon: Lock },
]
</script>
