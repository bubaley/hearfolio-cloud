<template>
  <AppAuthShell>
    <div
      v-if="query.isLoading.value"
      class="flex flex-col gap-3"
    >
      <AppSkeleton :lines="3" />
    </div>
    <AppResultState
      v-else-if="!organization"
      :icon="KeyRound"
      title="Вход через SSO не настроен"
      :description="
        notFound
          ? 'Для этой организации нет входа через провайдера. Проверьте ссылку или войдите по паролю'
          : 'Не удалось загрузить страницу входа. Проверьте соединение и попробуйте ещё раз'
      "
    >
      <template #actions>
        <AppButton
          variant="secondary"
          label="Войти по паролю"
          :to="{ name: 'auth' }"
        />
      </template>
    </AppResultState>
    <div
      v-else
      class="space-y-6"
    >
      <div class="space-y-1">
        <h1 class="text-xl font-semibold tracking-tight break-words">{{ organization.organization_name }}</h1>
        <p class="text-sm text-muted-foreground">
          {{
            organization.join_policy === 'provider'
              ? 'Войдите аккаунтом компании — доступ в организацию откроется автоматически'
              : 'Вход для участников организации через аккаунт компании'
          }}
        </p>
      </div>
      <AppAlert
        v-if="callbackError"
        tone="destructive"
        title="Не удалось войти через SSO"
        :description="callbackError"
      />
      <AppAlert
        v-else-if="required"
        tone="info"
        title="Нужен вход через SSO"
        description="Эта организация открывается только после входа через провайдера компании"
      />
      <div class="flex flex-col gap-2">
        <AppButton
          class="w-full"
          :icon="KeyRound"
          :label="organization.button_label || 'Войти через SSO'"
          :loading="startState.loading.value"
          @click="startState.execute"
        />
        <p
          v-if="startError"
          class="text-sm text-destructive"
          role="alert"
        >
          {{ startError }}
        </p>
      </div>
    </div>
    <template
      v-if="organization"
      #footer
    >
      <span v-if="isSignedIn && required">
        <NuxtLink
          :to="{ name: 'home-setup' }"
          class="underline underline-offset-4 hover:text-foreground"
          >Выбрать другую организацию</NuxtLink
        >
      </span>
      <span v-else-if="organization.login_mode === 'password_and_sso'">
        Есть пароль?
        <NuxtLink
          :to="{ name: 'auth', query: redirect ? { redirect } : {} }"
          class="underline underline-offset-4 hover:text-foreground"
          >Войти по паролю</NuxtLink
        >
      </span>
      <span v-else>Вход в эту организацию — только через провайдера компании</span>
    </template>
  </AppAuthShell>
</template>

<script setup lang="ts">
import { KeyRound } from '@lucide/vue'
import { useQuery } from '@pinia/colada'
import AppAuthShell from '~/shared/components/layout/AppAuthShell.vue'
import { isApiError } from '~/shared/api/client'
import { ssoOrganization } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'
import { ssoCallbackErrorMessage, ssoErrorMessage, useSsoStart } from '../composables/useSso'

const route = useRoute()
const client = useApiClient()
const { isSignedIn } = useSession()
const { start } = useSsoStart()

const key = computed(() => String(route.params.key ?? ''))
const redirect = computed(() => safeRedirect(route.query.redirect))
const required = computed(() => route.query.required === '1')
const callbackError = computed(() => ssoCallbackErrorMessage(route.query.sso_error))

const query = useQuery({
  key: () => ['sso-organization', key.value],
  query: async ({ signal }) =>
    (await ssoOrganization({ client, throwOnError: true, signal, path: { key: key.value } })).data,
})
const organization = computed(() => query.data.value ?? null)
const notFound = computed(() => isApiError(query.error.value, 404))

const startError = ref('')
const startState = useActionState(async () => {
  startError.value = ''
  try {
    await start({ organization_key: key.value, redirect: redirect.value })
  } catch (error) {
    startError.value = ssoErrorMessage(error, 'Не удалось начать вход. Попробуйте ещё раз')
  }
})

useHead({
  title: computed(() =>
    organization.value ? `Вход · ${organization.value.organization_name}` : `Вход через SSO · ${useAppConfig().name}`,
  ),
})
</script>
