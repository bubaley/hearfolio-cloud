<script setup lang="ts">
import { Moon, Sun } from '@lucide/vue'

/**
 * One-click light/dark switch for public pages (shared recording, landing) that have no profile menu.
 * Both icons are rendered and CSS picks one, so the server markup never depends on the visitor's theme.
 */
const { mode, resolvedMode } = useTheme()
const toggle = () => {
  mode.value = resolvedMode.value === 'dark' ? 'light' : 'dark'
}
</script>

<template>
  <AppButton
    variant="ghost"
    size="icon"
    text-variant="muted"
    class="size-11 md:size-control-md"
    aria-label="Переключить тему: светлая или тёмная"
    title="Светлая / тёмная тема"
    @click="toggle"
  >
    <!-- Wrappers: the icon's own display class would beat `hidden`. -->
    <span class="inline-flex dark:hidden">
      <AppIcon
        :icon="Moon"
        size="sm"
      />
    </span>
    <span class="hidden dark:inline-flex">
      <AppIcon
        :icon="Sun"
        size="sm"
      />
    </span>
  </AppButton>
</template>
