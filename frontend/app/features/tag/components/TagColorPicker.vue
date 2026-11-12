<template>
  <AppPopover
    v-model:open="open"
    label="Цвет тега"
    content-class="w-56"
  >
    <template #trigger>
      <slot name="trigger">
        <AppButton
          variant="outline"
          size="icon"
          :disabled="disabled"
          aria-label="Цвет тега"
          :title="model ? 'Цвет тега' : 'Цвет подберётся автоматически'"
        >
          <span
            class="size-4 rounded-sm border border-border-strong/40"
            :class="model ? tagChipClass(model) : 'border-dashed bg-transparent'"
          />
        </AppButton>
      </slot>
    </template>
    <div
      role="listbox"
      aria-label="Цвет тега"
      class="flex flex-col"
    >
      <button
        v-for="color in TAG_COLORS"
        :key="color.value"
        type="button"
        role="option"
        :aria-selected="model === color.value"
        class="flex h-11 items-center gap-2.5 rounded-md px-2 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent md:h-8"
        @click="pick(color.value)"
      >
        <span
          class="size-4 shrink-0 rounded-sm border border-border-strong/30"
          :class="color.chip"
        />
        <span class="flex-1">{{ color.label }}</span>
        <AppIcon
          v-if="model === color.value"
          :icon="Check"
          size="xs"
        />
      </button>
    </div>
  </AppPopover>
</template>

<script setup lang="ts">
import { Check } from '@lucide/vue'
import type { TagColor } from '../resources/tag'
import { TAG_COLORS, tagChipClass } from '../composables/tagColors'

defineProps<{ disabled?: boolean }>()
const model = defineModel<TagColor | null>({ default: null })
const open = ref(false)
const pick = (color: TagColor) => {
  model.value = color
  open.value = false
}
</script>
