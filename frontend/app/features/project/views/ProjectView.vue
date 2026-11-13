<template>
  <AppPageView content-class="px-4 pb-16 md:px-10">
    <div
      v-if="isLoading && !project"
      class="mx-auto flex w-full max-w-4xl flex-col gap-4 pt-10"
      aria-label="Загрузка"
    >
      <AppSkeleton class="size-14 rounded-lg" />
      <AppSkeleton class="h-9 max-w-md" />
      <AppSkeleton class="h-4 max-w-sm" />
    </div>

    <div
      v-else-if="!project"
      class="flex min-h-[60vh] items-center justify-center"
    >
      <div class="max-w-sm">
        <AppResultState
          :icon="notFound ? FolderX : CircleAlert"
          :tone="notFound ? 'muted' : 'destructive'"
          :title="notFound ? 'Проект не найден' : 'Не удалось загрузить проект'"
          :description="
            notFound
              ? 'Его удалили, или это приватный проект, в котором вас нет'
              : 'Проверьте соединение и попробуйте ещё раз'
          "
        >
          <template #actions>
            <AppButton
              v-if="!notFound"
              label="Повторить"
              :icon="RotateCw"
              @click="refetch()"
            />
            <AppButton
              variant="ghost"
              text-variant="muted"
              label="Все записи"
              :to="{ name: 'recordings' }"
            />
          </template>
        </AppResultState>
      </div>
    </div>

    <article
      v-else
      class="mx-auto flex w-full max-w-4xl flex-col gap-8 pt-8 md:pt-14"
    >
      <header class="flex flex-col gap-3">
        <div class="flex items-start justify-between gap-2">
          <AppEmojiPicker
            v-if="canEdit"
            :model-value="project.emoji"
            label="Иконка проекта"
            @update:model-value="(emoji) => patch({ emoji }, 'Не удалось сменить иконку')"
          >
            <template #trigger>
              <button
                type="button"
                class="-ml-1 rounded-lg p-1 outline-none hover:bg-field-hover focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="Сменить иконку проекта"
                title="Сменить иконку"
              >
                <ProjectIcon
                  :emoji="project.emoji"
                  size="lg"
                />
              </button>
            </template>
          </AppEmojiPicker>
          <ProjectIcon
            v-else
            :emoji="project.emoji"
            size="lg"
          />
          <AppMenu
            v-if="menuActions.some((action) => !action.hidden)"
            :actions="menuActions"
            content-class="w-60"
          >
            <template #trigger>
              <AppButton
                variant="ghost"
                size="icon"
                text-variant="muted"
                class="size-11 md:size-control-md"
                :icon="Ellipsis"
                aria-label="Действия с проектом"
              />
            </template>
          </AppMenu>
        </div>

        <h1 class="text-3xl leading-tight font-bold tracking-tight">
          <ProjectInlineText
            :value="project.name"
            :editable="canEdit"
            label="Название проекта"
            placeholder="Без названия"
            :maxlength="255"
            required
            as="span"
            @save="(name) => patch({ name }, 'Не удалось переименовать проект')"
          />
        </h1>

        <div class="flex flex-wrap items-center gap-2">
          <AppBadge
            :label="project.is_private ? 'Приватный' : 'Общий'"
            :icon="project.is_private ? Lock : Globe"
            :tone="project.is_private ? 'warning' : 'muted'"
          />
          <AppBadge
            v-if="project.archived_at"
            label="В архиве"
            :icon="Archive"
            tone="muted"
            variant="outline"
          />
          <button
            v-if="project.is_private"
            type="button"
            class="flex min-h-11 items-center gap-2 rounded-md px-1.5 text-sm text-muted-foreground outline-none hover:bg-field-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
            :aria-label="`Участники проекта: ${project.members.length}`"
            @click="dialog = 'members'"
          >
            <span class="flex -space-x-1.5">
              <AppAvatar
                v-for="member in project.members.slice(0, 5)"
                :key="member.user_id"
                :name="userDisplayName(member.user)"
                size="small"
                variant="soft"
                class="ring-2 ring-background"
              />
            </span>
            <span>{{ membersLabel }}</span>
          </button>
        </div>

        <div class="text-base text-muted-foreground">
          <ProjectInlineText
            :value="project.description"
            :editable="canEdit"
            label="Описание проекта"
            placeholder="Добавьте описание…"
            multiline
            :maxlength="2000"
            @save="(description) => patch({ description }, 'Не удалось сохранить описание')"
          />
        </div>
      </header>

      <ProjectRecordings :project-id="project.id" />
    </article>

    <ProjectDialogs
      v-model="dialog"
      :project="project ?? null"
      @deleted="navigateTo({ name: 'recordings' }, { replace: true })"
    />
  </AppPageView>
</template>

<script setup lang="ts">
import {
  Archive,
  ArchiveRestore,
  CircleAlert,
  Ellipsis,
  FolderX,
  Globe,
  Lock,
  RotateCw,
  Trash2,
  Unlock,
  Users,
} from '@lucide/vue'
import { isApiError } from '~/shared/api/client'
import type { ProjectUpdateSchema } from '~/shared/api/generated'
import { useResourceItem } from '~/shared/api/useResource'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import { projectResource } from '../resources/project'
import { projectErrorMessage, useProjectActions, useProjectPermissions } from '../composables/useProjects'
import { pluralize } from '../composables/projectLabels'
import ProjectIcon from '../components/ProjectIcon.vue'
import ProjectInlineText from '../components/ProjectInlineText.vue'
import ProjectDialogs, { type ProjectDialog } from '../components/ProjectDialogs.vue'
import ProjectRecordings from '../components/ProjectRecordings.vue'

const props = defineProps<{ id: string }>()

const toast = useToast()
const { data: project, isLoading, error, refetch } = useResourceItem(projectResource, () => props.id)
const notFound = computed(() => isApiError(error.value, 404))
const { canEdit, canManage } = useProjectPermissions(project)
const { update } = useProjectActions()

useHead({ title: () => (project.value ? project.value.name : 'Проект') })

const dialog = ref<ProjectDialog | null>(null)

const membersLabel = computed(() =>
  pluralize(project.value?.members.length ?? 0, ['участник', 'участника', 'участников']),
)

const patch = async (changes: ProjectUpdateSchema, failure: string, success?: string) => {
  if (!project.value) return
  try {
    await update.mutateAsync({ id: project.value.id, changes })
    if (success) toast.default(success)
  } catch (reason) {
    toast.error(projectErrorMessage(reason, failure))
  }
}

const menuActions = computed<AppMenuAction[]>(() => {
  const value = project.value
  if (!value) return []
  return [
    {
      label: 'Участники',
      icon: Users,
      hidden: !value.is_private,
      action: () => {
        dialog.value = 'members'
      },
    },
    {
      label: value.is_private ? 'Сделать общим' : 'Сделать приватным',
      icon: value.is_private ? Unlock : Lock,
      hidden: !canManage.value,
      action: () => {
        dialog.value = 'privacy'
      },
    },
    {
      label: value.archived_at ? 'Вернуть из архива' : 'Архивировать',
      icon: value.archived_at ? ArchiveRestore : Archive,
      hidden: !canEdit.value,
      action: () =>
        patch(
          { archived: !value.archived_at },
          'Не удалось изменить архив',
          value.archived_at ? 'Проект возвращён из архива' : 'Проект в архиве',
        ),
    },
    {
      label: 'Удалить',
      icon: Trash2,
      destructive: true,
      separatorBefore: true,
      hidden: !canManage.value,
      action: () => {
        dialog.value = 'delete'
      },
    },
  ]
})
</script>
