<template>
  <form
    class="flex flex-col gap-4"
    @submit.prevent="submitState.execute"
  >
    <AppInput
      v-model="form.name"
      label="Имя и фамилия"
      autocomplete="name"
      placeholder="Анна Смирнова"
      :error="fieldErrors.name"
      required
    />
    <AppInput
      v-model="form.email"
      label="Электронная почта"
      type="email"
      autocomplete="email"
      placeholder="name@company.ru"
      :error="fieldErrors.email"
      required
    />
    <AppInput
      v-model="form.password"
      label="Пароль"
      type="password"
      autocomplete="new-password"
      hint="Не короче 8 символов"
      :error="fieldErrors.password"
      required
    />
    <AppAlert
      v-if="emailExists"
      tone="warning"
      title="Этот email уже зарегистрирован"
    >
      Войдите в свою учётную запись — приглашение откроется снова.
      <AppTextButton
        label="Войти"
        weight="medium"
        :to="loginRoute"
      />
    </AppAlert>
    <AppButton
      type="submit"
      fluid
      label="Создать аккаунт и присоединиться"
      :loading="submitState.loading.value"
      :disabled="!form.name.trim() || !form.email.trim() || form.password.length < 8"
    />
  </form>
</template>

<script setup lang="ts">
import { invitesAccept, type InviteAcceptedSchema } from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { useApiClient } from '~/shared/api/useResource'
import { apiErrorReason, organizationErrorMessage } from '../../composables/organizationErrors'

const props = defineProps<{ token: string; loginRoute: { name: string; query: Record<string, string> } }>()
const emit = defineEmits<{ accepted: [result: InviteAcceptedSchema]; stale: [] }>()

const client = useApiClient()
const toast = useToast()
const form = reactive({ name: '', email: '', password: '' })
const emailExists = ref(false)
const fieldErrors = ref<Partial<Record<'name' | 'email' | 'password', string>>>({})
watch(
  () => ({ ...form }),
  () => {
    emailExists.value = false
    fieldErrors.value = {}
  },
)

const FIELD_MESSAGES = {
  name: 'Укажите имя',
  email: 'Проверьте адрес: такой email не подходит',
  password: 'Пароль не короче 8 символов',
} as const
// 422 `details.errors[].attribute` → a Russian message under the field.
const readFieldErrors = (error: unknown) => {
  const errors = isApiError(error) && Array.isArray(error.details?.errors) ? error.details.errors : []
  const result: typeof fieldErrors.value = {}
  for (const item of errors as { attribute?: string }[]) {
    const field = item.attribute as keyof typeof FIELD_MESSAGES | undefined
    if (field && FIELD_MESSAGES[field]) result[field] = FIELD_MESSAGES[field]
  }
  return result
}

const submitState = useActionState(async () => {
  try {
    const { data } = await invitesAccept({
      client,
      throwOnError: true,
      path: { token: props.token },
      body: { name: form.name.trim(), email: form.email.trim(), password: form.password },
    })
    emit('accepted', data)
  } catch (error) {
    const reason = apiErrorReason(error)
    if (reason === 'email_exists') emailExists.value = true
    else if (reason?.startsWith('invite_')) emit('stale')
    else if (isApiError(error, 422) || isApiError(error, 400)) {
      fieldErrors.value = readFieldErrors(error)
      if (!Object.keys(fieldErrors.value).length)
        toast.error('Проверьте данные', { description: 'Нужны имя, корректный email и пароль не короче 8 символов' })
    } else toast.error(organizationErrorMessage(error, 'Не удалось создать аккаунт. Попробуйте ещё раз'))
  }
})
</script>
