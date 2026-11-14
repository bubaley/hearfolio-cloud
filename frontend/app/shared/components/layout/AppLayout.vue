<template>
  <div class="flex h-dvh min-h-0 bg-background text-foreground">
    <a
      href="#main-content"
      class="sr-only z-overlay rounded-md bg-background px-3 py-2 text-sm font-medium shadow-overlay ring-2 ring-ring focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      @click.prevent="focusMain"
      >Перейти к содержимому</a
    >
    <aside
      v-show="!collapsed"
      class="hidden w-[264px] shrink-0 border-r border-sidebar-border bg-sidebar md:flex lg:w-[280px]"
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
      :width="320"
      :closeable="false"
      title="Навигация"
      content-class="p-0"
    >
      <AppSidebar
        class="h-full"
        sheet
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
      <!-- Narrow screens always; desktop only while the sidebar is hidden, and not over a page that has its own top
           bar (AppDocumentPage shows «Показать боковую панель» there): two stacked bars read as a mistake. -->
      <header
        class="flex h-12 shrink-0 items-center gap-1 border-b border-border px-1 md:px-2 md:[&:has(~main_[data-slot=page-topbar])]:hidden"
        :class="!collapsed && 'md:hidden'"
      >
        <AppButton
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="size-11 md:hidden"
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
      <main
        id="main-content"
        ref="mainRef"
        tabindex="-1"
        class="min-h-0 min-w-0 flex-1 overflow-auto outline-none"
      >
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
const mainRef = useTemplateRef<HTMLElement>('mainRef')

// The hash would change the route (and the main scroll); moving focus is all the skip link needs.
const focusMain = () => mainRef.value?.focus()

// A tap on a link in the sheet navigates; the sheet should not stay over the new page.
watch(
  () => route.fullPath,
  () => {
    mobileOpen.value = false
  },
)
</script>
