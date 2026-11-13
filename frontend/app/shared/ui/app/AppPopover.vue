<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '~/shared/lib/utils'
import { Popover, PopoverContent, PopoverTrigger } from '~/shared/ui/shadcn/popover'
import { useOverlayStack } from './useOverlayStack'

/**
 * Anchored floating panel (pickers, small forms, share settings). The `trigger` slot is rendered as the anchor
 * (`as-child`) and receives `open`; the default slot is the panel and receives `close`. Takes part in the overlay
 * stack like menus and modals. Menus of actions use `AppMenu`.
 */
withDefaults(
  defineProps<{
    align?: 'start' | 'center' | 'end'
    side?: 'top' | 'right' | 'bottom' | 'left'
    sideOffset?: number
    /** Accessible name of the panel. */
    label?: string
    contentClass?: HTMLAttributes['class']
    /** Keep focus on the trigger when the panel opens (panels whose first control should not grab focus). */
    preventOpenAutoFocus?: boolean
  }>(),
  { align: 'start', side: 'bottom', sideOffset: 6 },
)

const open = defineModel<boolean>('open', { default: false })
const { contentStyle } = useOverlayStack(open)
const close = () => {
  open.value = false
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <slot
        name="trigger"
        :open="open"
      />
    </PopoverTrigger>
    <PopoverContent
      :align="align"
      :side="side"
      :side-offset="sideOffset"
      :collision-padding="12"
      :aria-label="label"
      :class="
        cn(
          'max-h-(--reka-popover-content-available-height) max-w-[calc(100vw-24px)] overflow-y-auto p-2 shadow-overlay',
          contentClass,
        )
      "
      :style="contentStyle"
      @open-auto-focus="preventOpenAutoFocus && $event.preventDefault()"
    >
      <slot :close="close" />
    </PopoverContent>
  </Popover>
</template>
