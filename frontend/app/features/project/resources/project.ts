import {
  projectsCreate,
  projectsDestroy,
  projectsList,
  projectsPartialUpdate,
  projectsRetrieve,
  type LibraryUserSchema,
  type ProjectMemberReadSchema,
  type ProjectReadSchema,
} from '~/shared/api/generated'
import { defineResource } from '~/shared/api/resource'

export type Project = ProjectReadSchema
export type ProjectMember = ProjectMemberReadSchema
export type ProjectUser = LibraryUserSchema
export type ProjectForm = {
  id: string | null
  name: string
  emoji: string | null
  description: string
  is_private: boolean
}

export const projectResource = defineResource({
  key: 'projects',
  sdk: {
    // Visible projects (public + member of): the sidebar and pickers. Settings use `projectsManage`.
    list: projectsList,
    retrieve: projectsRetrieve,
    create: projectsCreate,
    update: projectsPartialUpdate,
    destroy: projectsDestroy,
  },
  toForm: (item?: Partial<Project>): ProjectForm => ({
    id: item?.id ?? null,
    name: item?.name ?? '',
    emoji: item?.emoji ?? null,
    description: item?.description ?? '',
    is_private: item?.is_private ?? false,
  }),
  toCreate: (form) => {
    const name = form.name.trim()
    if (!name) throw new Error('Введите название проекта')
    return { name, emoji: form.emoji, description: form.description.trim(), is_private: form.is_private }
  },
  toUpdate: (form) => ({ name: form.name.trim(), emoji: form.emoji, description: form.description.trim() }),
  // Recordings carry the project name and access.
  invalidates: ['recordings'],
})

export const userDisplayName = (user: Pick<ProjectUser, 'first_name' | 'last_name' | 'email'>) =>
  `${user.first_name} ${user.last_name}`.trim() || user.email
