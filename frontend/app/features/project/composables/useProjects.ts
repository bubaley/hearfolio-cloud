import { useMutation, useQuery, useQueryCache } from '@pinia/colada'
import {
  projectsAddMember,
  projectsManage,
  projectsPartialUpdate,
  projectsRemoveMember,
  type ProjectUpdateSchema,
} from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { resourceKeys } from '~/shared/api/resource'
import { invalidateResource, useApiClient, useResourceList, useResourceMutations } from '~/shared/api/useResource'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import { projectResource, type Project } from '../resources/project'

const SIDEBAR_PAGE_SIZE = 100

/** Visible, not archived projects for the sidebar; loads every page (organizations rarely have hundreds). */
export const useSidebarProjects = () => {
  const setupStore = useSetupStore()
  const list = useResourceList(projectResource, {
    params: () => ({ archived: false }),
    pageSize: SIDEBAR_PAGE_SIZE,
    enabled: () => Boolean(setupStore.state.organization),
  })
  watch(
    () => list.hasNextPage.value && !list.isLoading.value,
    (more) => {
      if (more) void list.loadNextPage()
    },
    { immediate: true },
  )
  return list
}

/** Settings list: visible projects plus every private one for org admins (`GET /projects/manage`). */
export const useManagedProjects = () => {
  const client = useApiClient()
  const setupStore = useSetupStore()
  return useQuery({
    key: [...resourceKeys(projectResource).all, 'manage'],
    query: async ({ signal }) => (await projectsManage({ client, throwOnError: true, signal })).data,
    enabled: () => Boolean(setupStore.state.organization),
  })
}

/** Partial updates, archive, delete and members of one project; every write refreshes the project queries. */
export const useProjectActions = () => {
  const client = useApiClient()
  const queryCache = useQueryCache()
  const { remove } = useResourceMutations(projectResource)
  const refresh = (project?: Project) => {
    if (project) queryCache.setQueryData(resourceKeys(projectResource).detail(project.id), project)
    return invalidateResource(queryCache, projectResource, project?.id)
  }

  const update = useMutation({
    mutation: async ({ id, changes }: { id: string; changes: ProjectUpdateSchema }) =>
      (await projectsPartialUpdate({ client, throwOnError: true, path: { item_id: id }, body: changes })).data,
    onSuccess: (project) => refresh(project),
  })

  const addMember = useMutation({
    mutation: async ({ id, userId }: { id: string; userId: string }) =>
      (await projectsAddMember({ client, throwOnError: true, path: { item_id: id }, body: { user_id: userId } })).data,
    onSettled: () => refresh(),
  })

  const removeMember = useMutation({
    mutation: async ({ id, userId }: { id: string; userId: string }) =>
      projectsRemoveMember({ client, throwOnError: true, path: { item_id: id, member: userId } }),
    onSettled: () => refresh(),
  })

  return { update, remove, addMember, removeMember }
}

/**
 * What the caller may do with a project, mirroring the backend (`ProjectService`): anyone edits a public project;
 * a private one is edited and staffed by its members and org admins; privacy and deletion belong to the creator
 * and org admins. The server still decides.
 */
export const useProjectPermissions = (project: MaybeRefOrGetter<Project | null | undefined>) => {
  const { user } = useSession()
  const { isAdmin } = useOrganizationRole()
  const isMember = computed(() => {
    const value = toValue(project)
    return Boolean(value && user.value && value.members.some((member) => member.user_id === user.value!.id))
  })
  const canEdit = computed(() => {
    const value = toValue(project)
    return Boolean(value && (!value.is_private || isMember.value || isAdmin.value))
  })
  const canManage = computed(() => {
    const value = toValue(project)
    return Boolean(value && (isAdmin.value || (user.value && value.created_by_id === user.value.id)))
  })
  return { isMember, canEdit, canManage }
}

/** Russian text for project API errors (backend messages are English). */
export const projectErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error && !isApiError(error) && error.message) return error.message
  if (isApiError(error, 403)) return 'Недостаточно прав для этого действия'
  if (isApiError(error, 404)) return 'Проект не найден или недоступен'
  if (isApiError(error, 409)) return 'Пользователь уже участник проекта'
  if (isApiError(error, 422) || isApiError(error, 400)) return 'Проверьте введённые данные'
  return fallback
}
