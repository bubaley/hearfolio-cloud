import { Folder, Lock, Plus } from '@lucide/vue'
import type { SidebarSection } from '~/shared/components/layout/sidebar/types'
import { useSidebarProjects } from './useProjects'

/** The workspace sidebar's «Проекты» section: visible projects (emoji, lock on private) and «+» for a new one. */
export const useProjectsSidebar = () => {
  const createOpen = ref(false)
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
      })),
  }))

  return { section, createOpen }
}
