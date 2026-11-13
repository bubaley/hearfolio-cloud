<template>
  <ProjectMembersModal
    v-if="project"
    :model-value="dialog === 'members'"
    :project="project"
    @update:model-value="close"
  />
  <AppConfirmModal
    :model-value="dialog === 'delete'"
    title="Удалить проект?"
    :subtitle="`«${project?.name ?? ''}» исчезнет у всех. Записи останутся — они просто будут без проекта.`"
    confirm-text="Удалить"
    :confirm-props="{ variant: 'destructive' }"
    :confirm="deleteProject"
    @update:model-value="close"
  />
  <AppConfirmModal
    :model-value="dialog === 'privacy'"
    :title="project?.is_private ? 'Сделать проект общим?' : 'Сделать проект приватным?'"
    :subtitle="
      project?.is_private
        ? 'Проект и его записи увидят все участники организации.'
        : 'Проект и его записи будут видеть только его участники. Вы станете участником, остальных можно добавить потом.'
    "
    :confirm-text="project?.is_private ? 'Сделать общим' : 'Сделать приватным'"
    :confirm="togglePrivacy"
    @update:model-value="close"
  />
</template>

<script setup lang="ts">
import type { Project } from '../resources/project'
import { projectErrorMessage, useProjectActions } from '../composables/useProjects'
import ProjectMembersModal from './ProjectMembersModal.vue'

export type ProjectDialog = 'members' | 'privacy' | 'delete'

/** Members, privacy and delete dialogs of one project, shared by the project page and the settings list. */
const props = defineProps<{ project: Project | null }>()
const dialog = defineModel<ProjectDialog | null>({ default: null })
const emit = defineEmits<{ deleted: [] }>()

const toast = useToast()
const { update, remove } = useProjectActions()

const close = (open: boolean | undefined) => {
  if (!open) dialog.value = null
}

const togglePrivacy = async () => {
  const project = props.project
  if (!project) return
  try {
    await update.mutateAsync({ id: project.id, changes: { is_private: !project.is_private } })
  } catch (error) {
    toast.error(projectErrorMessage(error, 'Не удалось изменить доступ'))
    return
  }
  dialog.value = null
  toast.default(project.is_private ? 'Проект стал общим' : 'Проект стал приватным')
}

const deleteProject = async () => {
  const project = props.project
  if (!project) return
  try {
    await remove.mutateAsync(project.id)
  } catch (error) {
    toast.error(projectErrorMessage(error, 'Не удалось удалить проект'))
    return
  }
  dialog.value = null
  toast.default('Проект удалён')
  emit('deleted')
}
</script>
