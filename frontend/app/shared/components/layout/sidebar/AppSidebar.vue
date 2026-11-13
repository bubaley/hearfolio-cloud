<template>
  <div class="flex min-h-0 flex-col">
    <div class="flex shrink-0 items-center gap-1 px-2 pt-2 pb-1">
      <div class="min-w-0 flex-1">
        <slot name="header" />
      </div>
      <!-- In the phone sheet the panel closes rather than hides, so it gets a plain close button. -->
      <AppButton
        variant="ghost"
        size="icon-sm"
        text-variant="muted"
        class="size-11 shrink-0 md:size-control-sm"
        :icon="sheet ? X : PanelLeftClose"
        :aria-label="sheet ? 'Закрыть навигацию' : 'Скрыть боковую панель'"
        :title="sheet ? 'Закрыть' : 'Скрыть боковую панель'"
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
import { PanelLeftClose, X } from '@lucide/vue'
import { provide } from 'vue'
import { SIDEBAR_IN_SHEET } from './types'

const props = defineProps<{
  /** Rendered in the phone sheet: a close button and no keyboard hints (there is no keyboard). */
  sheet?: boolean
}>()
const emit = defineEmits<{ hide: [] }>()

provide(SIDEBAR_IN_SHEET, props.sheet ?? false)
</script>
