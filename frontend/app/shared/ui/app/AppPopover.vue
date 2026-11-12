<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { Popover, PopoverContent, PopoverTrigger } from '~/shared/ui/shadcn/popover'
import { useOverlayStack } from './useOverlayStack'

/**
 * Anchored floating panel (pickers, small forms). The `trigger` slot is rendered as the anchor (`as-child`), the
 * default slot is the panel; `close` is passed to it. Takes part in the overlay stack like menus and modals.
 */
withDefaults(
  defineProps<{
    align?: 'start' | 'center' | 'end'
    side?: 'top' | 'right' | 'bottom' | 'left'
    /** Accessible name of the panel. */
    label?: string
    contentClass?: HTMLAttributes['class']
  }>(),
  { align: 'start', side: 'bottom' },
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
      <slot name="trigger" />
    </PopoverTrigger>
    <PopoverContent
      :align="align"
      :side="side"
      :side-offset="6"
      :collision-padding="12"
      :aria-label="label"
      :class="['max-w-[calc(100vw-24px)] p-2 shadow-overlay', contentClass]"
      :style="contentStyle"
    >
      <slot :close="close" />
    </PopoverContent>
  </Popover>
</template>
