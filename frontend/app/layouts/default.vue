<template>
  <AppLayout>
    <template #sidebar-header>
      <OrganizationSwitcher />
    </template>
    <template #topbar>
      <div class="flex min-w-0 items-center gap-1">
        <div class="min-w-0 flex-1">
          <OrganizationSwitcher />
        </div>
        <AppButton
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="size-11 shrink-0 md:size-control-md"
          :icon="Search"
          aria-label="Поиск записей"
          @click="quickSearch.show()"
        />
      </div>
    </template>
    <template #sidebar>
      <AppSidebarNav :sections="sections" />
    </template>
    <template #sidebar-footer>
      <AppSidebarLink :item="{ to: { name: 'settings' }, label: 'Настройки', icon: Settings }" />
      <AppSidebarUser />
    </template>
    <slot />
    <ProjectCreateModal v-model="createOpen" />
    <QuickSearchDialog />
    <UploadTray />
    <WelcomeModal />
  </AppLayout>
</template>

<script setup lang="ts">
import { Search, Settings } from '@lucide/vue'
import AppLayout from '~/shared/components/layout/AppLayout.vue'
import AppSidebarLink from '~/shared/components/layout/sidebar/AppSidebarLink.vue'
import AppSidebarNav from '~/shared/components/layout/sidebar/AppSidebarNav.vue'
import AppSidebarUser from '~/shared/components/layout/sidebar/AppSidebarUser.vue'
import type { SidebarItem, SidebarSection } from '~/shared/components/layout/sidebar/types'
import OrganizationSwitcher from '~/features/organization/components/OrganizationSwitcher.vue'
import WelcomeModal from '~/features/organization/components/WelcomeModal.vue'
import ProjectCreateModal from '~/features/project/components/ProjectCreateModal.vue'
import { useProjectsSidebar } from '~/features/project/composables/useProjectsSidebar'
import QuickSearchDialog from '~/features/recording/components/search/QuickSearchDialog.vue'
import UploadTray from '~/features/recording/components/upload/UploadTray.vue'
import { useQuickSearch } from '~/features/recording/composables/useQuickSearch'
import { useRecordingRealtime } from '~/features/recording/composables/useRecordingRealtime'
import { workspaceNavigation } from '~/navigation/workspace'

const quickSearch = useQuickSearch()
// Processing progress, renames and deletions from other members and the AI pipeline arrive here.
useRecordingRealtime()

const isMac = import.meta.client && /Mac|iPhone|iPad/.test(navigator.platform)
const searchItem: SidebarItem = {
  label: 'Поиск',
  icon: Search,
  hint: isMac ? '⌘K' : 'Ctrl K',
  onClick: quickSearch.show,
}

const { section: projectsSection, createOpen } = useProjectsSidebar()
const sections = computed<SidebarSection[]>(() => [
  { items: [searchItem, ...workspaceNavigation] },
  projectsSection.value,
])
</script>
