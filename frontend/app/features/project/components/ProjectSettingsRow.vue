<template>
  <li class="flex min-h-14 items-center gap-3 border-b border-border py-2 last:border-b-0">
    <ProjectIcon :emoji="project.emoji" />
    <div class="min-w-0 flex-1">
      <NuxtLink
        :to="{ name: 'projects-id', params: { id: project.id } }"
        class="block truncate text-sm font-medium outline-none hover:underline focus-visible:underline"
        >{{ project.name }}</NuxtLink
      >
      <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span class="inline-flex items-center gap-1">
          <AppIcon
            :icon="project.is_private ? Lock : Globe"
            size="xs"
          />
          {{ project.is_private ? 'Приватный' : 'Общий' }}
        </span>
        <span aria-hidden="true">·</span>
        <span>{{ project.is_private ? membersLabel : 'Все участники организации' }}</span>
        <template v-if="project.is_private && !isMember">
          <span aria-hidden="true">·</span>
          <span>вы не участник</span>
        </template>
        <AppBadge
          v-if="project.archived_at"
          label="В архиве"
          tone="muted"
          variant="outline"
        />
      </div>
    </div>
    <AppMenu
      v-if="actions.some((action) => !action.hidden)"
      :actions="actions"
      content-class="w-60"
    >
      <template #trigger>
        <AppButton
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="size-11 shrink-0 md:size-control-sm"
          :icon="Ellipsis"
          :loading="busy"
          :aria-label="`Действия: ${project.name}`"
        />
      </template>
    </AppMenu>
  </li>
</template>

<script setup lang="ts">
import { Archive, ArchiveRestore, Ellipsis, ExternalLink, Globe, Lock, Trash2, Unlock, Users } from '@lucide/vue'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import type { Project } from '../resources/project'
import { useProjectPermissions } from '../composables/useProjects'
import { pluralize } from '../composables/projectLabels'
import ProjectIcon from './ProjectIcon.vue'

const props = defineProps<{ project: Project; busy?: boolean }>()
const emit = defineEmits<{ members: []; privacy: []; archive: []; delete: [] }>()

const { canEdit, canManage, isMember } = useProjectPermissions(() => props.project)
const membersLabel = computed(() => pluralize(props.project.members.length, ['участник', 'участника', 'участников']))

const actions = computed<AppMenuAction[]>(() => [
  {
    label: 'Открыть',
    icon: ExternalLink,
    action: async () => {
      await navigateTo({ name: 'projects-id', params: { id: props.project.id } })
    },
  },
  { label: 'Участники', icon: Users, hidden: !props.project.is_private, action: () => emit('members') },
  {
    label: props.project.is_private ? 'Сделать общим' : 'Сделать приватным',
    icon: props.project.is_private ? Unlock : Lock,
    hidden: !canManage.value,
    action: () => emit('privacy'),
  },
  {
    label: props.project.archived_at ? 'Вернуть из архива' : 'Архивировать',
    icon: props.project.archived_at ? ArchiveRestore : Archive,
    hidden: !canEdit.value,
    action: () => emit('archive'),
  },
  {
    label: 'Удалить',
    icon: Trash2,
    destructive: true,
    separatorBefore: true,
    hidden: !canManage.value,
    action: () => emit('delete'),
  },
])
</script>
