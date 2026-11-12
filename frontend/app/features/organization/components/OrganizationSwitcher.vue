<template>
  <AppMenu
    :actions="actions"
    align="start"
    title="Организации"
    content-class="w-64"
  >
    <template #trigger>
      <button
        type="button"
        class="flex h-11 w-full min-w-0 items-center gap-2 rounded-md px-1.5 text-left transition-colors outline-none hover:bg-sidebar-accent/70 focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-sidebar-accent md:h-10"
        aria-label="Сменить организацию"
      >
        <span
          class="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary text-xs font-semibold text-primary-foreground"
          aria-hidden="true"
          >{{ initial }}</span
        >
        <span class="flex min-w-0 flex-1 flex-col leading-tight">
          <span class="truncate text-sm font-medium text-sidebar-foreground">{{ current?.name || 'Организация' }}</span>
          <span
            v-if="roleLabel"
            class="truncate text-xs text-muted-foreground"
            >{{ roleLabel.label }}</span
          >
        </span>
        <AppIcon
          :icon="ChevronsUpDown"
          size="xs"
          tone="muted"
        />
      </button>
    </template>
    <template #action="{ action }">
      <AppIcon
        v-if="action.icon"
        :icon="action.icon"
        aria-hidden="true"
      />
      <span class="flex min-w-0 flex-1 flex-col">
        <span class="truncate">{{ action.label }}</span>
        <span
          v-if="action.value && getRoleLabel(action.value as OrganizationRole)"
          class="text-xs text-muted-foreground"
          >{{ getRoleLabel(action.value as OrganizationRole)?.label }}</span
        >
      </span>
    </template>
  </AppMenu>
</template>

<script setup lang="ts">
import { Building2, ChevronsUpDown, Layers, Settings } from '@lucide/vue'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import { getRoleLabel, useOrganizationRole, type OrganizationRole } from '../composables/useOrganizationRole'

const setupStore = useSetupStore()
const { organizations } = useSession()
const { role } = useOrganizationRole()

// The session has the fresh name after a rename; the store keeps the one chosen at selection time.
const current = computed(() => {
  const selected = setupStore.state.organization
  return organizations.value.find((item) => item.id === selected?.id) ?? selected
})
const initial = computed(() => (current.value?.name || '?').trim().slice(0, 1).toUpperCase())
const roleLabel = computed(() => getRoleLabel(role.value))

const actions = computed<AppMenuAction[]>(() => [
  ...organizations.value.map((organization) => ({
    key: organization.id,
    label: organization.name,
    value: organization.role,
    icon: Building2,
    checked: organization.id === current.value?.id,
    action: async () => {
      if (organization.id === current.value?.id) return
      setupStore.state.organization = { id: organization.id, name: organization.name, key: organization.key }
      await navigateTo({ name: 'home' })
    },
  })),
  {
    key: 'settings',
    label: 'Настройки организации',
    icon: Settings,
    separatorBefore: true,
    action: async () => {
      await navigateTo({ name: 'settings-organization' })
    },
  },
  {
    key: 'all',
    label: 'Все организации',
    icon: Layers,
    action: async () => {
      await navigateTo({ name: 'home-setup' })
    },
  },
])
</script>
