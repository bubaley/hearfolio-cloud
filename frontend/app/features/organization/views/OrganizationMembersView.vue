<template>
  <AppPageView
    title="Участники"
    :description="description"
    content-class="px-4 pb-10"
  >
    <template #actions>
      <AppTemplateActions
        size="sm"
        :actions="headerActions"
      />
    </template>
    <div class="flex max-w-3xl flex-col gap-3 pt-2">
      <AppInput
        v-if="items.length > 6 || search"
        v-model="search"
        is-search
        clearable
        placeholder="Найти по имени или email"
        class="sm:max-w-xs"
        aria-label="Поиск участников"
      />
      <AppAlert
        v-if="error && !items.length"
        tone="destructive"
        title="Не удалось загрузить участников"
      >
        <AppTextButton
          label="Повторить"
          weight="medium"
          @click="refetch()"
        />
      </AppAlert>
      <ul
        v-else-if="isLoading && !items.length"
        aria-label="Загрузка"
      >
        <li
          v-for="row in 3"
          :key="row"
          class="flex h-14 items-center gap-3 border-b border-border last:border-b-0"
        >
          <AppSkeleton circle />
          <AppSkeleton
            :lines="2"
            class="max-w-xs"
          />
        </li>
      </ul>
      <ul v-else-if="visible.length">
        <MemberRow
          v-for="member in visible"
          :key="member.id"
          :member="member"
          :is-self="member.user_id === user?.id"
          :can-manage="isAdmin"
          :can-manage-owners="isOwner"
          :busy="busyId === member.id"
          @role="(role) => changeRole(member, role)"
          @remove="pendingRemove = member"
          @leave="confirmLeave = true"
        />
      </ul>
      <p
        v-else
        class="py-8 text-center text-sm text-muted-foreground"
      >
        {{ search ? 'Никого не нашли' : 'Пока никого нет' }}
      </p>
      <AppButton
        v-if="hasNextPage"
        variant="ghost"
        label="Показать ещё"
        :loading="isLoading"
        class="self-start"
        @click="loadNextPage()"
      />
    </div>

    <AppConfirmModal
      :model-value="Boolean(pendingRemove)"
      title="Удалить участника?"
      :subtitle="`${pendingRemoveName} потеряет доступ к записям и проектам организации.`"
      confirm-text="Удалить"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="removeMember"
      @update:model-value="(open) => !open && (pendingRemove = null)"
    />
    <AppConfirmModal
      v-model="confirmLeave"
      title="Покинуть организацию?"
      subtitle="Вы потеряете доступ к её записям. Вернуться можно только по новому приглашению."
      confirm-text="Покинуть"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="leave"
    />
    <OrganizationMemberAddModal
      v-if="isSuperuser && organizationId"
      v-model="addOpen"
      :organization-id="organizationId"
    />
  </AppPageView>
</template>

<script setup lang="ts">
import { LogOut, Mail, UserPlus } from '@lucide/vue'
import { useResourceList, useResourceMutations } from '~/shared/api/useResource'
import type { AppTemplateAction } from '~/shared/ui/template/types/template-types'
import MemberRow from '../components/member-list/MemberRow.vue'
import OrganizationMemberAddModal from '../components/member-list/OrganizationMemberAddModal.vue'
import { organizationUserResource, type OrganizationUser } from '../resources/organizationUser'
import { useOrganizationRole, type OrganizationRole } from '../composables/useOrganizationRole'
import { organizationErrorMessage } from '../composables/organizationErrors'

const setupStore = useSetupStore()
const { user } = useSession()
const { isAdmin, isOwner, isSuperuser, role: myRole } = useOrganizationRole()
const toast = useToast()

const organizationId = computed(() => setupStore.state.organization?.id ?? null)
const { items, isLoading, error, refetch, hasNextPage, loadNextPage } = useResourceList(organizationUserResource, {
  params: () => ({ organization_id: organizationId.value }),
  pageSize: 100,
  enabled: () => Boolean(organizationId.value),
})
const { save, remove } = useResourceMutations(organizationUserResource)

const search = ref('')
const visible = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return items.value
  return items.value.filter((member) =>
    [member.user.email, member.user.first_name, member.user.last_name].join(' ').toLowerCase().includes(query),
  )
})

const description = computed(() =>
  isAdmin.value
    ? 'Роли: владелец управляет всем, администратор — участниками и настройками, участник работает с записями'
    : 'Состав организации. Роли меняют владельцы и администраторы',
)

const membership = computed(() => items.value.find((member) => member.user_id === user.value?.id) ?? null)
const confirmLeave = ref(false)
const addOpen = ref(false)

const headerActions = computed<AppTemplateAction[]>(() => [
  {
    label: 'Покинуть',
    icon: LogOut,
    variant: 'ghost',
    textVariant: 'muted',
    hidden: !membership.value || !myRole.value,
    action: () => {
      confirmLeave.value = true
    },
  },
  {
    label: 'Добавить',
    icon: UserPlus,
    variant: 'outline',
    hidden: !isSuperuser.value,
    action: () => {
      addOpen.value = true
    },
  },
  {
    label: 'Пригласить',
    icon: Mail,
    hidden: !isAdmin.value,
    action: async () => {
      await navigateTo({ name: 'settings-invites' })
    },
  },
])

const busyId = ref<string | null>(null)
const changeRole = async (member: OrganizationUser, role: OrganizationRole) => {
  busyId.value = member.id
  try {
    await save.mutateAsync({ ...organizationUserResource.toForm(member), role })
    toast.default('Роль изменена')
  } catch (reason) {
    toast.error(organizationErrorMessage(reason, 'Не удалось изменить роль'))
  } finally {
    busyId.value = null
  }
}

const pendingRemove = ref<OrganizationUser | null>(null)
const pendingRemoveName = computed(() => {
  const member = pendingRemove.value?.user
  return member ? `${member.first_name} ${member.last_name}`.trim() || member.email : ''
})
const removeMember = async () => {
  const member = pendingRemove.value
  if (!member) return
  try {
    await remove.mutateAsync(member.id)
  } catch (reason) {
    toast.error(organizationErrorMessage(reason, 'Не удалось удалить участника'))
    return
  }
  pendingRemove.value = null
  toast.default('Участник удалён')
}

const leave = async () => {
  const current = membership.value
  if (!current) return
  try {
    await remove.mutateAsync(current.id)
  } catch (reason) {
    toast.error(organizationErrorMessage(reason, 'Не удалось покинуть организацию'))
    return
  }
  const name = setupStore.state.organization?.name
  setupStore.state.organization = null
  toast.default(name ? `Вы покинули «${name}»` : 'Вы покинули организацию')
  await navigateTo({ name: 'home-setup' }, { replace: true })
}
</script>
