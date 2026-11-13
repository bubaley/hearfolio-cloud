<template>
  <li class="flex min-h-14 items-center gap-3 border-b border-border py-2 last:border-b-0">
    <AppAvatar
      :name="displayName"
      variant="soft"
    />
    <div class="min-w-0 flex-1">
      <div class="flex min-w-0 items-center gap-2">
        <span class="truncate text-sm font-medium">{{ displayName }}</span>
        <AppBadge
          v-if="isSelf"
          label="Вы"
          tone="muted"
        />
      </div>
      <div
        v-if="hasName"
        class="truncate text-sm text-muted-foreground"
      >
        {{ member.user.email }}
      </div>
    </div>
    <AppMenu
      v-if="actions.length"
      :actions="actions"
      align="end"
      content-class="w-60"
    >
      <template #trigger>
        <AppButton
          variant="ghost"
          size="sm"
          text-variant="muted"
          class="h-11 shrink-0 md:h-control-sm"
          :icon="ChevronDown"
          icon-position="end"
          :label="roleLabel?.label"
          :loading="busy"
          :aria-label="`Роль и действия: ${displayName}`"
        />
      </template>
    </AppMenu>
    <span
      v-else
      class="shrink-0 px-2 text-sm text-muted-foreground"
      >{{ roleLabel?.label }}</span
    >
  </li>
</template>

<script setup lang="ts">
import { ChevronDown, LogOut, UserMinus } from '@lucide/vue'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import type { OrganizationUser } from '../../resources/organizationUser'
import { ROLE_LABELS, getRoleLabel, type OrganizationRole } from '../../composables/useOrganizationRole'

const props = defineProps<{
  member: OrganizationUser
  isSelf: boolean
  /** Caller is an org admin (owner, admin or superuser). */
  canManage: boolean
  /** Caller is an owner or a superuser. */
  canManageOwners: boolean
  busy?: boolean
}>()

const emit = defineEmits<{ role: [role: OrganizationRole]; remove: []; leave: [] }>()

const displayName = computed(() => userDisplayName(props.member.user))
const hasName = computed(() => displayName.value !== props.member.user.email)
const role = computed<OrganizationRole>(() => props.member.role ?? 'member')
const roleLabel = computed(() => getRoleLabel(role.value))

// Mirrors the backend rules so the menu offers only what can succeed; the server still decides.
const actions = computed<AppMenuAction[]>(() => {
  const touchesOwner = role.value === 'owner'
  const canEdit = props.canManage && (!touchesOwner || props.canManageOwners)
  const roles: OrganizationRole[] = props.canManageOwners ? ['owner', 'admin', 'member'] : ['admin', 'member']
  const result: AppMenuAction[] = canEdit
    ? roles.map((value) => ({
        key: value,
        label: ROLE_LABELS[value].label,
        icon: ROLE_LABELS[value].icon,
        checked: value === role.value,
        action: () => {
          if (value !== role.value) emit('role', value)
        },
      }))
    : []
  if (props.isSelf) {
    result.push({
      key: 'leave',
      label: 'Покинуть организацию',
      icon: LogOut,
      destructive: true,
      separatorBefore: result.length > 0,
      action: () => emit('leave'),
    })
  } else if (canEdit) {
    result.push({
      key: 'remove',
      label: 'Удалить из организации',
      icon: UserMinus,
      destructive: true,
      separatorBefore: true,
      action: () => emit('remove'),
    })
  }
  return result
})
</script>
