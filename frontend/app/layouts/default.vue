<template>
  <AppLayout>
    <template #sidebar-header>
      <OrganizationSwitcher />
    </template>
    <template #topbar>
      <OrganizationSwitcher />
    </template>
    <template #sidebar>
      <AppSidebarNav :sections="sections" />
    </template>
    <template #sidebar-footer>
      <AppSidebarLink :item="{ to: { name: 'settings' }, label: 'Настройки', icon: Settings }" />
      <AppSidebarUser />
    </template>
    <slot />
  </AppLayout>
</template>

<script setup lang="ts">
import { Settings } from '@lucide/vue'
import AppLayout from '~/shared/components/layout/AppLayout.vue'
import AppSidebarLink from '~/shared/components/layout/sidebar/AppSidebarLink.vue'
import AppSidebarNav from '~/shared/components/layout/sidebar/AppSidebarNav.vue'
import AppSidebarUser from '~/shared/components/layout/sidebar/AppSidebarUser.vue'
import type { SidebarSection } from '~/shared/components/layout/sidebar/types'
import OrganizationSwitcher from '~/features/organization/components/OrganizationSwitcher.vue'
import { workspaceNavigation } from '~/navigation/workspace'

// «Проекты» stays empty until the projects screens exist; they fill `items` and the «+» action.
const sections: SidebarSection[] = [
  { items: workspaceNavigation },
  { title: 'Проекты', items: [], empty: 'Проектов пока нет' },
]
</script>
