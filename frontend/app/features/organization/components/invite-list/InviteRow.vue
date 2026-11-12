<template>
  <li class="flex min-h-14 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border py-2.5 last:border-b-0">
    <div class="flex min-w-0 flex-1 basis-56 flex-col gap-0.5">
      <div class="flex min-w-0 flex-wrap items-center gap-2">
        <span class="text-sm font-medium">{{ roleLabel?.label }}</span>
        <AppBadge
          :icon="stateLabel.icon"
          :tone="stateLabel.tone"
          :label="stateLabel.label"
        />
      </div>
      <div class="truncate text-sm text-muted-foreground">{{ details }}</div>
    </div>
    <AppButton
      v-if="invite.state === 'valid'"
      variant="ghost"
      size="sm"
      text-variant="muted"
      class="h-11 md:h-control-sm"
      label="Отозвать"
      :icon="Ban"
      @click="emit('revoke')"
    />
  </li>
</template>

<script setup lang="ts">
import { Ban } from '@lucide/vue'
import type { UserReadSchema } from '~/shared/api/generated'
import type { OrganizationInvite } from '../../resources/organizationInvite'
import { getInviteStateLabel } from '../../composables/useInviteLabels'
import { getRoleLabel } from '../../composables/useOrganizationRole'

const props = defineProps<{ invite: OrganizationInvite }>()
const emit = defineEmits<{ revoke: [] }>()

// Instants: parse as datetime (local zone) and show the day only.
const { formatDate, parseDate } = useDate()
const roleLabel = computed(() => getRoleLabel(props.invite.role))
const stateLabel = computed(() => getInviteStateLabel(props.invite.state))

const personName = (user: UserReadSchema | null) =>
  user ? `${user.first_name} ${user.last_name}`.trim() || user.email : null

const details = computed(() => {
  const invite = props.invite
  const day = formatDate(parseDate(invite.created_at), { type: 'date', disableRelative: true })
  const created = invite.created_by ? `${personName(invite.created_by)}, ${day}` : `Создано ${day}`
  if (invite.state === 'used') {
    const who = personName(invite.accepted_by)
    return `${who ? `Принял ${who}` : 'Принято'} ${formatDate(parseDate(invite.accepted_at), { type: 'date', disableRelative: true }) ?? ''}`.trim()
  }
  if (invite.state === 'revoked')
    return `${created} · отозвано ${formatDate(parseDate(invite.revoked_at), { type: 'date', disableRelative: true }) ?? ''}`
  if (invite.state === 'expired')
    return `${created} · истекло ${formatDate(parseDate(invite.expires_at), { type: 'date', disableRelative: true })}`
  return `${created} · действует до ${formatDate(invite.expires_at, { disableRelative: true })}`
})
</script>
