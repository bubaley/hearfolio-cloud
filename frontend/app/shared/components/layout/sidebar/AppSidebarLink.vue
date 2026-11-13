<template>
  <component
    :is="item.to ? NuxtLink : 'button'"
    v-bind="item.to ? { to: item.to } : { type: 'button' }"
    :aria-current="active ? 'page' : undefined"
    class="flex h-11 w-full min-w-0 items-center gap-2.5 rounded-md px-2 text-left text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring md:h-8"
    :class="
      active
        ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
        : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground'
    "
    @click="item.onClick?.()"
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
      v-if="item.hint"
      class="shrink-0 text-xs text-muted-foreground"
      >{{ item.hint }}</span
    >
  </component>
</template>

<script setup lang="ts">
import { NuxtLink } from '#components'
import type { SidebarItem } from './types'

defineProps<{ item: SidebarItem; active?: boolean }>()
</script>
