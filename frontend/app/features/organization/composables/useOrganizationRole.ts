import { Crown, ShieldCheck, User } from '@lucide/vue'
import type { OrganizationRole } from '~/shared/api/generated'
import type { AppLabelConfig } from '~/shared/ui/app/types/label-types'

export type { OrganizationRole }

export const ROLE_LABELS: Record<OrganizationRole, AppLabelConfig> = {
  owner: { label: 'Владелец', icon: Crown, tone: 'primary' },
  admin: { label: 'Администратор', icon: ShieldCheck, tone: 'info' },
  member: { label: 'Участник', icon: User, tone: 'muted' },
}

export const getRoleLabel = (role: OrganizationRole | null | undefined) => (role ? ROLE_LABELS[role] : null)

/**
 * The caller's role in the selected organization (from the session). Superusers act as org admins everywhere and
 * as owners where they are not members, mirroring the backend rule.
 */
export const useOrganizationRole = () => {
  const { user, organizations } = useSession()
  const setupStore = useSetupStore()

  const role = computed<OrganizationRole | null>(() => {
    const id = setupStore.state.organization?.id
    return organizations.value.find((item) => item.id === id)?.role ?? null
  })
  const isSuperuser = computed(() => Boolean(user.value?.is_superuser))
  const isOwner = computed(() => role.value === 'owner' || isSuperuser.value)
  const isAdmin = computed(() => role.value === 'admin' || isOwner.value)

  return { role, isAdmin, isOwner, isSuperuser }
}
