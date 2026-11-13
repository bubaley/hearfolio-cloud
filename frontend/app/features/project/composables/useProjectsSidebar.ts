import { Folder, Lock, Plus } from '@lucide/vue'
import type { SidebarSection } from '~/shared/components/layout/sidebar/types'
import type { ProjectBrief } from '../resources/project'
import { useSidebarProjects } from './useProjects'

/** Open state of «Новый проект», shared by the sidebar «+» and the ⌘K palette. */
export const useProjectCreate = () => useState('project-create-open', () => false)

/**
 * The workspace sidebar's «Проекты» section: visible projects (emoji, lock on private) and «+» for a new one.
 * `drop` makes every project a drop target for that drag type (recordings dragged from a list).
 */
export const useProjectsSidebar = (drop?: { accepts: string; onDrop: (project: ProjectBrief) => void }) => {
  const createOpen = useProjectCreate()
  const { items, isLoading, error } = useSidebarProjects()

  const section = computed<SidebarSection>(() => ({
    title: 'Проекты',
    collapsibleId: 'projects',
    limit: 8,
    loading: isLoading.value,
    empty: error.value ? 'Не удалось загрузить проекты' : 'Проектов пока нет',
    action: {
      label: 'Новый проект',
      icon: Plus,
      onClick: () => {
        createOpen.value = true
      },
    },
    items: [...items.value]
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
      .map((project) => ({
        to: { name: 'projects-id', params: { id: project.id } },
        label: project.name,
        emoji: project.emoji ?? undefined,
        icon: Folder,
        trailingIcon: project.is_private ? Lock : undefined,
        trailingLabel: project.is_private ? 'Приватный' : undefined,
        drop: drop && {
          accepts: drop.accepts,
          onDrop: () =>
            drop.onDrop({ id: project.id, name: project.name, emoji: project.emoji, is_private: project.is_private }),
        },
      })),
  }))

  return { section, createOpen }
}
