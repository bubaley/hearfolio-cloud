<template>
  <AppAuthShell>
    <div
      v-if="info.isLoading.value && !request"
      class="flex flex-col items-center gap-4 py-2"
      aria-label="Проверяем запрос"
    >
      <AppSkeleton circle />
      <AppSkeleton
        :lines="2"
        class="max-w-60"
      />
    </div>

    <AppResultState
      v-else-if="invalid"
      :icon="ShieldX"
      tone="destructive"
      title="Не удалось подключить приложение"
      :description="invalid"
    >
      <template #actions>
        <AppButton
          fluid
          variant="outline"
          label="Открыть Hearfolio"
          :to="{ name: 'home' }"
        />
      </template>
    </AppResultState>

    <AppResultState
      v-else-if="outcome === 'approved'"
      :icon="CircleCheck"
      tone="success"
      title="Можно вернуться в приложение"
      :description="`Hearfolio на «${request?.device_name}» подключён к вашей учётной записи. Эту вкладку можно закрыть`"
    />

    <AppResultState
      v-else-if="outcome === 'denied'"
      :icon="CircleSlash"
      title="Подключение отменено"
      description="Приложение не получило доступ. Эту вкладку можно закрыть"
    />

    <div
      v-else-if="request"
      class="flex flex-col gap-6"
    >
      <header class="flex flex-col items-center gap-3 text-center">
        <span
          class="flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground"
          aria-hidden="true"
        >
          <AppIcon
            :icon="MonitorSmartphone"
            size="md"
          />
        </span>
        <div class="flex flex-col gap-1">
          <h1 class="text-lg font-semibold text-balance">
            Подключить {{ request.client_name }} на «{{ request.device_name }}»?
          </h1>
          <p class="text-sm text-balance text-muted-foreground">
            Приложение сможет загружать записи и читать данные ваших организаций от вашего имени
          </p>
        </div>
      </header>

      <div class="flex items-center gap-3 rounded-lg border border-border px-3 py-2.5">
        <AppAvatar
          :name="accountName"
          variant="soft"
        />
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-medium">{{ accountName }}</div>
          <div class="truncate text-xs text-muted-foreground">{{ user?.email }}</div>
        </div>
      </div>

      <div class="flex flex-col gap-2">
        <AppButton
          fluid
          label="Подключить"
          :loading="approveState.loading.value"
          :disabled="denying"
          @click="approveState.execute"
        />
        <AppButton
          fluid
          variant="secondary"
          label="Отмена"
          :disabled="approveState.loading.value"
          :loading="denying"
          @click="deny"
        />
      </div>
      <p class="text-center text-xs text-muted-foreground">
        Отключить устройство можно в профиле, в разделе «Подключённые устройства»
      </p>
    </div>
  </AppAuthShell>
</template>

<script setup lang="ts">
import { useQuery } from '@pinia/colada'
import { CircleCheck, CircleSlash, MonitorSmartphone, ShieldX } from '@lucide/vue'
import { oauthAuthorize, oauthAuthorizeInfo, type OAuthAuthorizeRequest } from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { useApiClient } from '~/shared/api/useResource'
import AppAuthShell from '~/shared/components/layout/AppAuthShell.vue'

const route = useRoute()
const client = useApiClient()
const toast = useToast()
const { user } = useSession()

const param = (name: string) => {
  const value = route.query[name]
  return typeof value === 'string' ? value : undefined
}
// Exactly what the app sent; the server validates it, the page never trusts it on its own.
const params = computed<OAuthAuthorizeRequest>(() => ({
  client_id: param('client_id') ?? '',
  redirect_uri: param('redirect_uri') ?? '',
  code_challenge: param('code_challenge') ?? '',
  code_challenge_method: param('code_challenge_method') ?? 'S256',
  state: param('state') ?? null,
  device_name: param('device_name') ?? '',
}))

const info = useQuery({
  key: () => ['oauth-authorize', JSON.stringify(params.value)],
  query: async ({ signal }) =>
    (await oauthAuthorizeInfo({ client, throwOnError: true, signal, query: params.value })).data,
  refetchOnWindowFocus: false,
})
const request = computed(() => info.data.value ?? null)

const ERRORS: Record<string, string> = {
  invalid_client: 'Неизвестное приложение. Обновите Hearfolio и попробуйте подключиться снова',
  invalid_request: 'Приложение прислало неполный или неверный запрос. Начните подключение в приложении заново',
}
const invalid = computed(() => {
  const error = info.error.value
  if (!error) return null
  if (isApiError(error, 403)) return 'Войдите в браузере под своей учётной записью и начните подключение заново'
  const code = isApiError(error) ? error.details?.error : null
  return (typeof code === 'string' && ERRORS[code]) || 'Проверьте соединение и начните подключение в приложении заново'
})

const accountName = computed(
  () => `${user.value?.first_name ?? ''} ${user.value?.last_name ?? ''}`.trim() || user.value?.email || '',
)

const outcome = ref<'approved' | 'denied' | null>(null)
// `hearfolio://…` or a loopback URL the server validated: leave the page for the app. The code inside is single-use
// (a replay revokes the token), so the page never offers to open it again.
const openApp = (url: string) => window.location.assign(url)

const approveState = useActionState(async () => {
  try {
    const { data } = await oauthAuthorize({ client, throwOnError: true, body: params.value })
    outcome.value = 'approved'
    openApp(data.redirect_to)
  } catch (error) {
    if (isApiError(error, 400)) await info.refetch()
    else toast.error('Не удалось подключить приложение. Попробуйте ещё раз')
  }
})

// Only the redirect URI the server accepted (GET /oauth/authorize) receives the denial.
const denying = ref(false)
const deny = () => {
  const target = request.value?.redirect_uri
  if (!target) return
  denying.value = true
  const url = new URL(target)
  url.searchParams.set('error', 'access_denied')
  if (params.value.state) url.searchParams.set('state', params.value.state)
  outcome.value = 'denied'
  openApp(url.toString())
}
</script>
