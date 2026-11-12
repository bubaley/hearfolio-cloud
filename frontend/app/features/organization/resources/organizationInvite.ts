import {
  organizationInvitesCreate,
  organizationInvitesList,
  organizationInvitesRetrieve,
  type InviteState,
  type OrganizationInviteCreatedSchema,
  type OrganizationInviteReadSchema,
  type OrganizationRole,
} from '~/shared/api/generated'
import { defineResource } from '~/shared/api/resource'

export type OrganizationInvite = OrganizationInviteReadSchema
/** The create response: the only time the token and the link are returned. */
export type CreatedInvite = OrganizationInviteCreatedSchema
export type { InviteState }
export type OrganizationInviteForm = {
  id: string | null
  role: Exclude<OrganizationRole, 'owner'>
  expires_in_days: number
}

// Invites of the selected organization (`Organization-Key`); org admins only. Revoke is an action, not an update.
export const organizationInviteResource = defineResource({
  key: 'organization-invites',
  sdk: {
    list: organizationInvitesList,
    retrieve: organizationInvitesRetrieve,
    create: organizationInvitesCreate,
  },
  toForm: (item?: Partial<OrganizationInvite>): OrganizationInviteForm => ({
    id: item?.id ?? null,
    role: item?.role === 'admin' ? 'admin' : 'member',
    expires_in_days: 7,
  }),
  toCreate: (form) => ({ role: form.role, expires_in_days: form.expires_in_days }),
})
