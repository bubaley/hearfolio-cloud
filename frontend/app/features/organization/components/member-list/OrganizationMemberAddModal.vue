<template>
  <AppModal
    v-model="open"
    title="Добавить участника"
    description="Существующий пользователь сервера сразу получит доступ. Новых людей удобнее звать по приглашению"
  >
    <form
      class="flex flex-col gap-4"
      @submit.prevent="submitState.execute"
    >
      <AppSelect
        v-model="form.user"
        label="Пользователь"
        :resource="userResource"
        option-label="email"
        placeholder="Выберите пользователя"
      />
      <AppField label="Роль">
        <AppRadioGroup
          v-model="form.role"
          :items="roleItems"
        />
      </AppField>
    </form>
    <template #footer>
      <AppTemplateActions
        full-width
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          { label: 'Добавить', loading: submitState.loading.value, disabled: !form.user, action: submitState.execute },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { userResource } from '~/features/user/resources/user'
import { useResourceMutations } from '~/shared/api/useResource'
import { organizationUserResource } from '../../resources/organizationUser'
import { ROLE_LABELS, type OrganizationRole } from '../../composables/useOrganizationRole'
import { organizationErrorMessage } from '../../composables/organizationErrors'

const props = defineProps<{ organizationId: string }>()
const open = defineModel<boolean>({ default: false })

const toast = useToast()
const { save } = useResourceMutations(organizationUserResource)
const form = ref(organizationUserResource.toForm({ organization_id: props.organizationId }))
watch(open, (value) => {
  if (value) form.value = organizationUserResource.toForm({ organization_id: props.organizationId })
})

const roleItems = (['member', 'admin', 'owner'] as OrganizationRole[]).map((value) => ({
  label: ROLE_LABELS[value].label,
  value,
}))

const submitState = useActionState(async () => {
  try {
    await save.mutateAsync(form.value)
  } catch (error) {
    toast.error(organizationErrorMessage(error, 'Не удалось добавить участника'))
    throw error
  }
  toast.default('Участник добавлен')
  open.value = false
})
</script>
