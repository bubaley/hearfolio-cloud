<script setup lang="ts">
import { SmilePlus } from '@lucide/vue'
import { EMOJI_GROUPS } from './emojiCatalog'

/**
 * Small curated emoji grid in a popover (project icons). `v-model` is the emoji or `null`; «Убрать» clears it.
 * The `trigger` slot replaces the default button; it receives `{ value }`.
 */
withDefaults(
  defineProps<{
    label?: string
    disabled?: boolean
    /** Offer «Убрать» (back to the default icon). */
    clearable?: boolean
  }>(),
  { label: 'Выбрать эмодзи', clearable: true },
)

const model = defineModel<string | null>({ default: null })
const open = ref(false)

const pick = (emoji: string | null) => {
  model.value = emoji
  open.value = false
}
</script>

<template>
  <AppPopover
    v-model:open="open"
    :label="label"
    content-class="w-[min(20rem,calc(100vw-24px))]"
  >
    <template #trigger>
      <slot
        name="trigger"
        :value="model"
      >
        <AppButton
          variant="outline"
          size="icon"
          :disabled="disabled"
          :aria-label="label"
          :title="label"
        >
          <span
            v-if="model"
            class="text-lg leading-none"
            >{{ model }}</span
          >
          <AppIcon
            v-else
            :icon="SmilePlus"
            size="sm"
            class="text-muted-foreground"
          />
        </AppButton>
      </slot>
    </template>
    <div class="flex max-h-72 flex-col gap-2 overflow-y-auto">
      <section
        v-for="group in EMOJI_GROUPS"
        :key="group.label"
      >
        <h3 class="px-1 pb-1 text-xs font-medium text-muted-foreground">{{ group.label }}</h3>
        <div class="grid grid-cols-8 gap-0.5">
          <button
            v-for="emoji in group.items"
            :key="emoji"
            type="button"
            class="flex aspect-square items-center justify-center rounded-md text-xl leading-none outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
            :class="model === emoji && 'bg-accent'"
            :aria-label="emoji"
            :aria-pressed="model === emoji"
            @click="pick(emoji)"
          >
            {{ emoji }}
          </button>
        </div>
      </section>
    </div>
    <div
      v-if="clearable && model"
      class="mt-2 border-t border-border pt-2"
    >
      <AppButton
        variant="ghost"
        size="sm"
        text-variant="muted"
        label="Убрать"
        fluid
        @click="pick(null)"
      />
    </div>
  </AppPopover>
</template>
