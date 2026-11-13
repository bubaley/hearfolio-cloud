<template>
  <AppLayout>
    <template #sidebar-header>
      <AppSidebarLink :item="{ to: { name: 'home' }, label: 'Назад', icon: ArrowLeft }" />
    </template>
    <template #topbar>
      <span class="px-1 text-sm font-medium">Настройки</span>
    </template>
    <template #sidebar>
      <div
        v-if="hasOrganization"
        class="pb-3"
      >
        <OrganizationSwitcher />
      </div>
      <AppSidebarNav :sections="sections" />
    </template>
    <template #sidebar-footer>
      <AppSidebarUser />
    </template>
    <slot />
  </AppLayout>
</template>

<script setup lang="ts">
import { ArrowLeft } from '@lucide/vue'
import AppLayout from '~/shared/components/layout/AppLayout.vue'
import AppSidebarLink from '~/shared/components/layout/sidebar/AppSidebarLink.vue'
import AppSidebarNav from '~/shared/components/layout/sidebar/AppSidebarNav.vue'
import AppSidebarUser from '~/shared/components/layout/sidebar/AppSidebarUser.vue'
import type { SidebarSection } from '~/shared/components/layout/sidebar/types'
import OrganizationSwitcher from '~/features/organization/components/OrganizationSwitcher.vue'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import { settingsNavigation, settingsSections } from '~/navigation/settings'
import { PAGE_CONTAINER_CLASS } from '~/shared/ui/app/pageContainer'

// Every settings screen shares one centered column; header actions stay at its edge on wide screens.
provide(PAGE_CONTAINER_CLASS, 'max-w-3xl')

const setupStore = useSetupStore()
const { isAdmin, isSuperuser } = useOrganizationRole()
const hasOrganization = computed(() => Boolean(setupStore.state.organization))

const sections = computed<SidebarSection[]>(() =>
  settingsSections
    .map(({ key, title }) => ({
      title,
      items: settingsNavigation
        .filter((item) => (item.section ?? 'organization') === key)
        // The profile works before an organization is chosen; the organization pages do not.
        .filter((item) => key !== 'organization' || hasOrganization.value)
        .filter((item) => (!item.adminOnly || isAdmin.value) && (!item.superuserOnly || isSuperuser.value)),
    }))
    .filter((section) => section.items.length),
)
</script>
