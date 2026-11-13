<template>
  <AppModal
    v-model="open"
    title="Участники"
    :description="
      canEdit
        ? 'Проект и его записи видят только участники. Добавлять и убирать их могут участники проекта и администраторы'
        : 'Проект и его записи видят только участники'
    "
    width="34rem"
  >
    <div class="flex flex-col gap-4">
      <ul class="flex flex-col">
        <li
          v-for="member in sortedMembers"
          :key="member.user_id"
          class="flex min-h-12 items-center gap-3 border-b border-border py-1.5 last:border-b-0"
        >
          <AppAvatar
            :name="userDisplayName(member.user)"
            variant="soft"
          />
          <div class="min-w-0 flex-1">
            <div class="flex min-w-0 items-center gap-2">
              <span class="truncate text-sm font-medium">{{ userDisplayName(member.user) }}</span>
              <AppBadge
                v-if="member.user_id === selfId"
                label="Вы"
                tone="muted"
              />
              <AppBadge
                v-if="member.user_id === project.created_by_id"
                label="Создатель"
                tone="muted"
                variant="outline"
              />
            </div>
            <div
              v-if="userDisplayName(member.user) !== member.user.email"
              class="truncate text-xs text-muted-foreground"
            >
              {{ member.user.email }}
            </div>
          </div>
          <AppButton
            v-if="canEdit"
            variant="ghost"
            size="sm"
            text-variant="muted"
            class="h-11 shrink-0 md:h-control-sm"
            :label="member.user_id === selfId ? 'Выйти' : 'Убрать'"
            :loading="busyId === member.user_id"
            :aria-label="`${member.user_id === selfId ? 'Выйти из проекта' : 'Убрать из проекта'}: ${userDisplayName(member.user)}`"
            @click="askRemove(member)"
          />
        </li>
      </ul>
      <p
        v-if="!project.members.length"
        class="text-sm text-muted-foreground"
      >
        В проекте пока никого нет
      </p>

      <section
        v-if="canEdit"
        class="flex flex-col gap-2 border-t border-border pt-4"
      >
        <h3 class="text-sm font-medium">Добавить участников</h3>
        <ProjectMemberPicker
          v-model="toAdd"
          :exclude-ids="project.members.map((member) => member.user_id)"
          empty-text="Все участники организации уже в проекте"
        />
        <AppButton
          v-if="toAdd.length"
          :label="`Добавить · ${toAdd.length}`"
          :icon="UserPlus"
          :loading="addState.loading.value"
          class="self-start"
          @click="addState.execute"
        />
      </section>
    </div>

    <AppConfirmModal
      :model-value="Boolean(pendingRemove)"
      :title="pendingRemove?.user_id === selfId ? 'Выйти из проекта?' : 'Убрать участника?'"
      :subtitle="
        pendingRemove?.user_id === selfId
          ? 'Вы перестанете видеть проект и его записи. Вернуть доступ сможет участник проекта или администратор.'
          : `${pendingRemove ? userDisplayName(pendingRemove.user) : ''} перестанет видеть проект и его записи.`
      "
      :confirm-text="pendingRemove?.user_id === selfId ? 'Выйти' : 'Убрать'"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="removeMember"
      @update:model-value="(value) => !value && (pendingRemove = null)"
    />
  </AppModal>
</template>

<script setup lang="ts">
import { UserPlus } from '@lucide/vue'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import type { Project, ProjectMember } from '../resources/project'
import { projectErrorMessage, useProjectActions, useProjectPermissions } from '../composables/useProjects'
import ProjectMemberPicker from './ProjectMemberPicker.vue'

const props = defineProps<{ project: Project }>()
const open = defineModel<boolean>({ default: false })

const toast = useToast()
const { user } = useSession()
const { isAdmin } = useOrganizationRole()
const selfId = computed(() => user.value?.id ?? null)
const { canEdit } = useProjectPermissions(() => props.project)
const { addMember, removeMember: removeMutation } = useProjectActions()

const sortedMembers = computed(() =>
  [...props.project.members].sort((a, b) => {
    if (a.user_id === selfId.value) return -1
    if (b.user_id === selfId.value) return 1
    return userDisplayName(a.user).localeCompare(userDisplayName(b.user), 'ru')
  }),
)

const toAdd = ref<string[]>([])
watch(open, (value) => {
  if (value) toAdd.value = []
})

const addState = useActionState(async () => {
  const ids = [...toAdd.value]
  const results = await Promise.allSettled(ids.map((userId) => addMember.mutateAsync({ id: props.project.id, userId })))
  const failed = results.filter((result) => result.status === 'rejected')
  toAdd.value = ids.filter((_, index) => results[index]!.status === 'rejected')
  if (failed.length) {
    toast.error(projectErrorMessage((failed[0] as PromiseRejectedResult).reason, 'Не удалось добавить участников'))
    return
  }
  toast.default(ids.length === 1 ? 'Участник добавлен' : 'Участники добавлены')
})

const pendingRemove = ref<ProjectMember | null>(null)
const busyId = ref<string | null>(null)
const askRemove = (member: ProjectMember) => {
  pendingRemove.value = member
}
const removeMember = async () => {
  const member = pendingRemove.value
  if (!member) return
  busyId.value = member.user_id
  try {
    await removeMutation.mutateAsync({ id: props.project.id, userId: member.user_id })
  } catch (error) {
    toast.error(projectErrorMessage(error, 'Не удалось убрать участника'))
    return
  } finally {
    busyId.value = null
  }
  pendingRemove.value = null
  if (member.user_id === selfId.value && !isAdmin.value) {
    open.value = false
    toast.default('Вы вышли из проекта')
    await navigateTo({ name: 'home' })
    return
  }
  toast.default('Участник убран')
}
</script>
