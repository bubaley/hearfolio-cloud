<template>
  <NuxtLink
    :to="item.to"
    :aria-current="active ? 'page' : undefined"
    class="flex h-11 min-w-0 items-center gap-2.5 rounded-md px-2 text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring md:h-8"
    :class="
      active
        ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
        : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground'
    "
  >
    <AppIcon
      v-if="item.icon"
      :icon="item.icon"
      size="sm"
      class="shrink-0"
      :class="active ? 'opacity-100' : 'opacity-70'"
    />
    <span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
    <span
      v-if="item.hint"
      class="shrink-0 text-xs text-muted-foreground"
      >{{ item.hint }}</span
    >
  </NuxtLink>
</template>

<script setup lang="ts">
import type { SidebarItem } from './types'

defineProps<{ item: SidebarItem; active?: boolean }>()
</script>
