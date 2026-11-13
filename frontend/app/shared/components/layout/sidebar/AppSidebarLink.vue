<template>
  <component
    :is="item.to ? NuxtLink : 'button'"
    v-bind="item.to ? { to: item.to } : { type: 'button' }"
    :aria-current="active ? 'page' : undefined"
    class="flex h-11 w-full min-w-0 items-center gap-2.5 rounded-md px-2 text-left text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring md:h-8"
    :class="[
      active
        ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
        : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground',
      dropping && 'ring-2 ring-ring',
    ]"
    @click="item.onClick?.()"
    @dragover="onDragOver"
    @dragleave="dropping = false"
    @drop="onDrop"
  >
    <span
      v-if="item.emoji"
      class="flex size-4 shrink-0 items-center justify-center text-sm leading-none"
      aria-hidden="true"
      >{{ item.emoji }}</span
    >
    <AppIcon
      v-else-if="item.icon"
      :icon="item.icon"
      size="sm"
      class="shrink-0"
      :class="active ? 'opacity-100' : 'opacity-70'"
    />
    <span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
    <AppIcon
      v-if="item.trailingIcon"
      :icon="item.trailingIcon"
      size="xs"
      class="shrink-0 text-muted-foreground"
      :aria-label="item.trailingLabel"
      :aria-hidden="item.trailingLabel ? undefined : 'true'"
      role="img"
    />
    <span
      v-if="item.hint && !inSheet"
      class="shrink-0 text-xs text-muted-foreground"
      >{{ item.hint }}</span
    >
  </component>
</template>

<script setup lang="ts">
import { NuxtLink } from '#components'
import { inject } from 'vue'
import { SIDEBAR_IN_SHEET, type SidebarItem } from './types'

const props = defineProps<{ item: SidebarItem; active?: boolean }>()
const inSheet = inject(SIDEBAR_IN_SHEET, false)

// Optional drop target (`item.drop`): highlighted while a matching drag hovers it.
const dropping = ref(false)
const accepts = (event: DragEvent) =>
  Boolean(props.item.drop && event.dataTransfer?.types.includes(props.item.drop.accepts))
const onDragOver = (event: DragEvent) => {
  if (!accepts(event)) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dropping.value = true
}
const onDrop = (event: DragEvent) => {
  if (!accepts(event)) return
  event.preventDefault()
  dropping.value = false
  props.item.drop!.onDrop()
}
</script>
