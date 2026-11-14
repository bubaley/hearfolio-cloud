<template>
  <AppDocumentPage>
    <template
      v-if="!project"
      #state
    >
      <div
        v-if="isLoading"
        class="flex flex-col gap-4"
        aria-label="Загрузка"
      >
        <AppSkeleton class="size-14 rounded-lg" />
        <AppSkeleton class="h-9 max-w-md" />
        <AppSkeleton class="h-4 max-w-sm" />
      </div>

      <div
        v-else
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
    </template>

    <template
      v-if="project"
      #icon
    >
      <AppEmojiPicker
        v-if="canEdit"
        :model-value="project.emoji"
        label="Иконка проекта"
        @update:model-value="(emoji) => patch({ emoji }, 'Не удалось сменить иконку')"
      >
        <template #trigger>
          <button
            type="button"
            class="-m-1 rounded-lg p-1 outline-none hover:bg-field-hover focus-visible:ring-2 focus-visible:ring-ring"
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
    </template>

    <template
      v-if="project"
      #lead
    >
      <span class="flex min-w-0 items-center gap-2 px-3 md:px-2">
        <ProjectIcon :emoji="project.emoji" />
        <span class="truncate">{{ project.name || 'Без названия' }}</span>
      </span>
    </template>

    <template
      v-if="project && (showUpload || hasMenu)"
      #actions
    >
      <AppButton
        v-if="showUpload"
        variant="ghost"
        :icon="Upload"
        label="Загрузить"
        text-variant="muted"
        @click="recordings?.pickFiles()"
      />
      <AppMenu
        v-if="hasMenu"
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
    </template>

    <template
      v-if="project"
      #title
    >
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
    </template>

    <template
      v-if="project"
      #meta
    >
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
    </template>

    <template
      v-if="project"
      #description
    >
      <ProjectInlineText
        :value="project.description"
        :editable="canEdit"
        label="Описание проекта"
        placeholder="Добавьте описание…"
        multiline
        :maxlength="2000"
        @save="(description) => patch({ description }, 'Не удалось сохранить описание')"
      />
    </template>

    <template v-if="project">
      <AppAlert
        v-if="project.archived_at"
        tone="info"
        :icon="Archive"
        title="Проект в архиве"
      >
        <p>Его нет в боковой панели и в выборе проекта, загрузка сюда выключена. Записи остаются доступны</p>
        <AppTextButton
          v-if="canEdit"
          label="Вернуть из архива"
          weight="medium"
          @click="setArchived(false)"
        />
      </AppAlert>

      <!-- Org admins open private projects they are not in: the list would be empty, not because there is nothing. -->
      <section
        v-if="project.is_private && !isMember"
        aria-label="Записи проекта"
        class="flex justify-center rounded-xl border border-dashed border-border px-4 py-10"
      >
        <div class="w-full max-w-sm">
          <AppResultState
            :icon="Lock"
            title="Записи этого проекта видны только участникам"
            :description="
              canEdit
                ? 'Вы администратор: добавьте себя в участники, чтобы видеть записи проекта'
                : 'Попросите участника проекта добавить вас'
            "
          >
            <template
              v-if="canEdit && user"
              #actions
            >
              <AppButton
                :icon="UserPlus"
                label="Добавить себя"
                :loading="joinState.loading.value"
                @click="joinState.execute"
              />
            </template>
          </AppResultState>
        </div>
      </section>
      <ProjectRecordings
        v-else
        ref="recordings"
        :project-id="project.id"
        :can-upload="!project.archived_at"
      />
    </template>

    <ProjectDialogs
      v-model="dialog"
      :project="project ?? null"
      @deleted="navigateTo({ name: 'recordings' }, { replace: true })"
    />
  </AppDocumentPage>
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
  Upload,
  UserPlus,
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
const { canEdit, canManage, isMember } = useProjectPermissions(project)
const { update, addMember } = useProjectActions()

useHead({ title: () => (project.value ? project.value.name : 'Проект') })

const dialog = ref<ProjectDialog | null>(null)

// Header actions, as on every page: «Загрузить» first, the «⋯» menu last.
const recordings = ref<{ pickFiles: () => void }>()
const showUpload = computed(() =>
  Boolean(project.value && !project.value.archived_at && (!project.value.is_private || isMember.value)),
)
const hasMenu = computed(() => menuActions.value.some((action) => !action.hidden))

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

/** Archive or bring back; archiving offers «Отменить» (the project leaves the sidebar at once). */
const setArchived = async (archived: boolean) => {
  if (!project.value) return
  const id = project.value.id
  try {
    await update.mutateAsync({ id, changes: { archived } })
  } catch (reason) {
    toast.error(projectErrorMessage(reason, 'Не удалось изменить архив'))
    return
  }
  if (!archived) {
    toast.default('Проект возвращён из архива')
    return
  }
  toast.default('Проект в архиве', {
    description: 'Он пропал из боковой панели; записи остались на месте',
    duration: 8000,
    action: {
      label: 'Отменить',
      onClick: () =>
        void update
          .mutateAsync({ id, changes: { archived: false } })
          .catch((reason) => toast.error(projectErrorMessage(reason, 'Не удалось вернуть проект'))),
    },
  })
}

// An org admin may add themselves to any private project (docs/product.md → Project).
const { user } = useSession()
const joinState = useActionState(async () => {
  if (!project.value || !user.value) return
  try {
    await addMember.mutateAsync({ id: project.value.id, userId: user.value.id })
    toast.default('Вы добавлены в проект')
  } catch (reason) {
    toast.error(projectErrorMessage(reason, 'Не удалось добавить вас в проект'))
  }
})

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
      action: () => setArchived(!value.archived_at),
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
