<template>
  <div class="flex h-dvh min-h-0 bg-background text-foreground">
    <aside
      v-show="!collapsed"
      class="hidden w-60 shrink-0 border-r border-sidebar-border bg-sidebar md:flex lg:w-64"
      aria-label="Боковая панель"
    >
      <AppSidebar
        class="w-full"
        @hide="collapsed = true"
      >
        <template #header>
          <slot name="sidebar-header" />
        </template>
        <slot name="sidebar" />
        <template #footer>
          <slot name="sidebar-footer" />
        </template>
      </AppSidebar>
    </aside>

    <AppDrawer
      v-model="mobileOpen"
      overlay
      side="left"
      :width="296"
      :closeable="false"
      title="Навигация"
      content-class="p-0"
    >
      <AppSidebar
        class="h-full"
        @hide="mobileOpen = false"
      >
        <template #header>
          <slot name="sidebar-header" />
        </template>
        <slot name="sidebar" />
        <template #footer>
          <slot name="sidebar-footer" />
        </template>
      </AppSidebar>
    </AppDrawer>

    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <!-- Narrow screens always; desktop only while the sidebar is hidden. -->
      <header
        class="flex h-12 shrink-0 items-center gap-1 border-b border-border px-2"
        :class="!collapsed && 'md:hidden'"
      >
        <AppButton
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="md:hidden"
          :icon="Menu"
          aria-label="Открыть навигацию"
          @click="mobileOpen = true"
        />
        <AppButton
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="hidden md:inline-flex"
          :icon="PanelLeftOpen"
          aria-label="Показать боковую панель"
          @click="collapsed = false"
        />
        <div class="min-w-0 flex-1">
          <slot name="topbar" />
        </div>
      </header>
      <main class="min-h-0 min-w-0 flex-1 overflow-auto">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Menu, PanelLeftOpen } from '@lucide/vue'
import AppSidebar from './sidebar/AppSidebar.vue'

const { collapsed, mobileOpen } = useSidebar()
const route = useRoute()

// A tap on a link in the sheet navigates; the sheet should not stay over the new page.
watch(
  () => route.fullPath,
  () => {
    mobileOpen.value = false
  },
)
</script>
