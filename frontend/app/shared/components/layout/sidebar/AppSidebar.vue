<template>
  <div class="flex min-h-0 flex-col">
    <div class="flex shrink-0 items-center gap-1 px-2 pt-2 pb-1">
      <div class="min-w-0 flex-1">
        <slot name="header" />
      </div>
      <AppButton
        variant="ghost"
        size="icon-sm"
        text-variant="muted"
        class="size-11 shrink-0 md:size-control-sm"
        :icon="PanelLeftClose"
        aria-label="Скрыть боковую панель"
        title="Скрыть боковую панель"
        @click="emit('hide')"
      />
    </div>
    <div class="min-h-0 flex-1 overflow-y-auto px-2 py-2">
      <slot />
    </div>
    <div
      v-if="$slots.footer"
      class="flex shrink-0 flex-col gap-px border-t border-sidebar-border px-2 py-2"
    >
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { PanelLeftClose } from '@lucide/vue'

const emit = defineEmits<{ hide: [] }>()
</script>
