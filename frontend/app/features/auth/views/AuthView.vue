<template>
  <AppAuthShell>
    <div class="space-y-6">
      <div class="space-y-1">
        <h1 class="text-xl font-semibold tracking-tight">Войти</h1>
        <p class="text-sm text-muted-foreground">Используйте учётную запись вашей команды</p>
      </div>
      <AppAlert
        v-if="ssoCallbackError"
        tone="destructive"
        title="Не удалось войти через SSO"
        :description="ssoCallbackError"
      />
      <form
        v-if="ssoMode"
        class="space-y-4"
        novalidate
        @submit.prevent="ssoState.execute"
      >
        <AppInput
          id="sso-target"
          v-model="ssoTarget"
          label="Рабочая почта или ключ организации"
          autocomplete="username"
          placeholder="name@company.ru"
          autofocus
          :error="ssoError"
        />
        <AppButton
          :disabled="!ssoTarget.trim()"
          :loading="ssoState.loading.value"
          type="submit"
          class="w-full"
          :icon="KeyRound"
        >
          Продолжить
        </AppButton>
        <AppButton
          variant="ghost"
          text-variant="muted"
          type="button"
          class="w-full"
          label="Войти по паролю"
          @click="ssoMode = false"
        />
      </form>
      <form
        v-else
        class="space-y-4"
        novalidate
        @submit.prevent="loginHandler"
      >
        <AppInput
          id="email"
          v-model="email"
          label="Электронная почта"
          type="email"
          autocomplete="username"
          placeholder="name@company.ru"
          autofocus
          required
          :aria-invalid="Boolean(error) || undefined"
        />
        <AppInput
          id="password"
          v-model="password"
          label="Пароль"
          :type="passwordVisible ? 'text' : 'password'"
          autocomplete="current-password"
          required
          :error="error"
        >
          <template #append>
            <AppButton
              variant="ghost"
              size="icon-sm"
              text-variant="muted"
              type="button"
              :icon="passwordVisible ? EyeOff : Eye"
              :aria-label="passwordVisible ? 'Скрыть пароль' : 'Показать пароль'"
              :aria-pressed="passwordVisible"
              @click="passwordVisible = !passwordVisible"
            />
          </template>
        </AppInput>
        <AppButton
          :disabled="!email || !password"
          :loading="login.isLoading.value"
          type="submit"
          class="w-full"
        >
          Войти
        </AppButton>
        <AppButton
          variant="secondary"
          type="button"
          class="w-full"
          :icon="KeyRound"
          label="Войти через SSO"
          @click="ssoMode = true"
        />
      </form>
    </div>
    <template #footer>Забыли пароль? Попросите администратора сбросить его</template>
  </AppAuthShell>
</template>

<script setup lang="ts">
import { Eye, EyeOff, KeyRound } from '@lucide/vue'
import AppAuthShell from '~/shared/components/layout/AppAuthShell.vue'
import { isApiError } from '~/shared/api/client'
import { ssoCallbackErrorMessage, ssoErrorMessage, useSsoStart } from '~/features/sso/composables/useSso'

const email = ref('')
const password = ref('')
const passwordVisible = ref(false)
const error = ref('')
const router = useRouter()
const { login } = useSession()

// A stale message under the field would contradict what the user is typing now.
watch([email, password], () => {
  error.value = ''
})

const loginHandler = async () => {
  if (login.isLoading.value || !email.value || !password.value) return
  error.value = ''
  try {
    await login.mutateAsync({ email: email.value.trim(), password: password.value })
  } catch (failure) {
    if (isApiError(failure, 401) || isApiError(failure, 400)) error.value = 'Неверная почта или пароль'
    else if (isApiError(failure, 429)) error.value = 'Слишком много попыток входа. Попробуйте позже'
    else error.value = 'Не удалось войти. Проверьте соединение и попробуйте ещё раз'
    return
  }
  await router.replace(safeRedirect(router.currentRoute.value.query.redirect) ?? { name: 'home' })
}

// «Войти через SSO»: a work email (its domain finds the organization) or the organization key.
const route = useRoute()
const { start } = useSsoStart()
const ssoMode = ref(false)
const ssoTarget = ref('')
const ssoError = ref('')
const ssoCallbackError = computed(() => ssoCallbackErrorMessage(route.query.sso_error))
watch(ssoTarget, () => {
  ssoError.value = ''
})
watch(ssoMode, async (sso) => {
  await nextTick()
  document.getElementById(sso ? 'sso-target' : 'email')?.focus()
})
const ssoState = useActionState(async () => {
  const target = ssoTarget.value.trim()
  if (!target) return
  ssoError.value = ''
  const redirect = safeRedirect(route.query.redirect)
  try {
    await start(target.includes('@') ? { email: target, redirect } : { organization_key: target, redirect })
  } catch (failure) {
    ssoError.value = ssoErrorMessage(failure, 'Не удалось начать вход через SSO')
  }
})

useHead({ title: `Вход · ${useAppConfig().name}` })
</script>
