<template>
  <AppPageView
    title="Проекты"
    :description="
      isAdmin
        ? 'Все проекты организации, включая приватные. Записи приватного проекта видят только его участники'
        : 'Проекты, которые вам доступны. Приватные видят только их участники'
    "
    content-class="px-4 pb-10"
  >
    <template #actions>
      <AppButton
        size="sm"
        label="Новый проект"
        :icon="Plus"
        @click="createOpen = true"
      />
    </template>
    <div class="flex max-w-3xl flex-col gap-3 pt-2">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
        <AppInput
          v-model="search"
          is-search
          clearable
          placeholder="Найти проект"
          aria-label="Поиск проектов"
          class="sm:max-w-xs"
        />
        <AppTabs
          v-model="scope"
          :tabs="scopes"
          query-key="scope"
          aria-label="Какие проекты показать"
        />
      </div>
      <AppAlert
        v-if="error && !projects"
        tone="destructive"
        title="Не удалось загрузить проекты"
      >
        <AppTextButton
          label="Повторить"
          weight="medium"
          @click="refetch()"
        />
      </AppAlert>
      <ul
        v-else-if="isLoading && !projects"
        aria-label="Загрузка"
      >
        <li
          v-for="row in 4"
          :key="row"
          class="flex h-14 items-center gap-3 border-b border-border last:border-b-0"
        >
          <AppSkeleton class="size-5" />
          <AppSkeleton
            :lines="2"
            class="max-w-xs"
          />
        </li>
      </ul>
      <ul v-else-if="visible.length">
        <ProjectSettingsRow
          v-for="project in visible"
          :key="project.id"
          :project="project"
          :busy="busyId === project.id"
          @members="open(project, 'members')"
          @privacy="open(project, 'privacy')"
          @delete="open(project, 'delete')"
          @archive="toggleArchive(project)"
        />
      </ul>
      <div
        v-else
        class="py-10"
      >
        <AppResultState
          :icon="FolderOpen"
          :title="emptyTitle"
          :description="search ? 'Попробуйте другое название' : undefined"
        />
      </div>
    </div>

    <ProjectDialogs
      v-model="dialog"
      :project="selected"
    />
    <ProjectCreateModal v-model="createOpen" />
  </AppPageView>
</template>

<script setup lang="ts">
import { FolderOpen, Plus } from '@lucide/vue'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import type { Project } from '../resources/project'
import { projectErrorMessage, useManagedProjects, useProjectActions } from '../composables/useProjects'
import ProjectCreateModal from '../components/ProjectCreateModal.vue'
import ProjectDialogs, { type ProjectDialog } from '../components/ProjectDialogs.vue'
import ProjectSettingsRow from '../components/ProjectSettingsRow.vue'

const { isAdmin } = useOrganizationRole()
const toast = useToast()
const { data: projects, isLoading, error, refetch } = useManagedProjects()
const { update } = useProjectActions()

const scope = ref('active')
const scopes = [
  { label: 'Активные', value: 'active' },
  { label: 'В архиве', value: 'archived' },
  { label: 'Все', value: 'all' },
]
const search = ref('')

const visible = computed(() => {
  const query = search.value.trim().toLowerCase()
  return (projects.value ?? [])
    .filter((project) => scope.value === 'all' || (scope.value === 'archived') === Boolean(project.archived_at))
    .filter((project) => !query || project.name.toLowerCase().includes(query))
    .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
})
const emptyTitle = computed(() => {
  if (search.value) return 'Ничего не нашли'
  if (scope.value === 'archived') return 'В архиве пусто'
  return 'Проектов пока нет'
})

const createOpen = ref(false)
const dialog = ref<ProjectDialog | null>(null)
const selectedId = ref<string | null>(null)
// Follow the fresh list so an open dialog shows updated members.
const selected = computed(() => projects.value?.find((project) => project.id === selectedId.value) ?? null)
const open = (project: Project, kind: ProjectDialog) => {
  selectedId.value = project.id
  dialog.value = kind
}

const busyId = ref<string | null>(null)
const toggleArchive = async (project: Project) => {
  busyId.value = project.id
  try {
    await update.mutateAsync({ id: project.id, changes: { archived: !project.archived_at } })
    toast.default(project.archived_at ? 'Проект возвращён из архива' : 'Проект в архиве')
  } catch (reason) {
    toast.error(projectErrorMessage(reason, 'Не удалось изменить архив'))
  } finally {
    busyId.value = null
  }
}
</script>
