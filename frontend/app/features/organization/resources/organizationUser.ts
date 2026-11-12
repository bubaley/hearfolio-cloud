import {
  organizationUsersCreate,
  organizationUsersDestroy,
  organizationUsersList,
  organizationUsersRetrieve,
  organizationUsersUpdate,
  type OrganizationRole,
  type OrganizationUserReadSchema,
  type UserReadSchema,
} from '~/shared/api/generated'
import { defineResource } from '~/shared/api/resource'

export type OrganizationUser = OrganizationUserReadSchema
export type OrganizationUserForm = {
  id: string | null
  organization_id: string
  user: UserReadSchema | null
  role: OrganizationRole
}

export const organizationUserResource = defineResource({
  key: 'organization-users',
  sdk: {
    list: organizationUsersList,
    retrieve: organizationUsersRetrieve,
    create: organizationUsersCreate,
    update: organizationUsersUpdate,
    destroy: organizationUsersDestroy,
  },
  toForm: (item?: Partial<OrganizationUser>): OrganizationUserForm => ({
    id: item?.id ?? null,
    organization_id: item?.organization_id ?? '',
    user: item?.user ?? null,
    role: item?.role ?? 'member',
  }),
  // The organization comes from the body (the organization being viewed), not from `Organization-Key`.
  toCreate: (form) => {
    if (!form.organization_id || !form.user) throw new Error('Выберите пользователя')
    return { organization_id: form.organization_id, user_id: form.user.id, role: form.role }
  },
  // Only the role changes; the backend checks owner/admin rules (403 `not_admin`/`not_owner`, 409 `last_owner`).
  toUpdate: (form) => ({ role: form.role }),
  // Adding the current user or changing their role changes the session's organizations.
  invalidates: ['session'],
})
