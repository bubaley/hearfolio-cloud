<template>
  <AppAuthShell>
    <div
      v-if="(preview.isLoading.value && !invite) || sessionPending"
      class="flex flex-col items-center gap-4 py-2"
      aria-label="Загрузка приглашения"
    >
      <AppSkeleton circle />
      <AppSkeleton
        :lines="2"
        class="max-w-60"
      />
    </div>

    <AppResultState
      v-else-if="loadError"
      :icon="loadError.icon"
      :tone="loadError.tone"
      :title="loadError.title"
      :description="loadError.description"
    >
      <template #actions>
        <AppButton
          v-if="loadError.retry"
          fluid
          variant="outline"
          label="Повторить"
          @click="preview.refetch()"
        />
        <AppButton
          fluid
          variant="ghost"
          label="На главную"
          to="/"
        />
      </template>
    </AppResultState>

    <AppResultState
      v-else-if="alreadyMember"
      :icon="UsersRound"
      tone="success"
      title="Вы уже в этой организации"
      :description="`«${invite?.organization_name}» уже есть в вашем списке. Ссылка осталась неиспользованной`"
    >
      <template #actions>
        <AppButton
          fluid
          label="Открыть Hearfolio"
          @click="openApp()"
        />
      </template>
    </AppResultState>

    <AppResultState
      v-else-if="invite && invite.state !== 'valid'"
      :icon="closedState.icon"
      tone="warning"
      :title="closedState.title"
      description="Попросите администратора организации прислать новую ссылку"
    >
      <template
        v-if="isSignedIn"
        #actions
      >
        <AppButton
          fluid
          variant="outline"
          label="Открыть Hearfolio"
          :to="{ name: 'home' }"
        />
      </template>
    </AppResultState>

    <div
      v-else-if="invite"
      class="flex flex-col gap-6"
    >
      <header class="flex flex-col items-center gap-3 text-center">
        <span
          class="flex size-12 items-center justify-center rounded-xl bg-primary text-lg font-semibold text-primary-foreground"
          aria-hidden="true"
          >{{ invite.organization_name.trim().slice(0, 1).toUpperCase() }}</span
        >
        <div class="flex flex-col gap-1">
          <h1 class="text-lg font-semibold text-balance">Приглашение в «{{ invite.organization_name }}»</h1>
          <p class="text-sm text-balance text-muted-foreground">
            <template v-if="invite.inviter_name">{{ invite.inviter_name }} приглашает вас</template>
            <template v-else>Вас приглашают</template>
            с ролью «{{ roleLabel?.label.toLowerCase() }}». Ссылка действует до {{ expiresAt }}
          </p>
        </div>
      </header>

      <div
        v-if="isSignedIn"
        class="flex flex-col gap-3"
      >
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
        <AppButton
          fluid
          label="Присоединиться"
          :loading="joinState.loading.value"
          @click="joinState.execute"
        />
        <AppButton
          fluid
          variant="ghost"
          text-variant="muted"
          label="Это не я — выйти"
          :loading="logout.isLoading.value"
          @click="switchAccount"
        />
      </div>

      <template v-else>
        <InviteRegisterForm
          :token="token"
          :login-route="loginRoute"
          @accepted="onAccepted"
          @stale="preview.refetch()"
        />
        <p class="text-center text-sm text-muted-foreground">
          Уже есть аккаунт?
          <AppTextButton
            label="Войти"
            weight="medium"
            tone="primary"
            :to="loginRoute"
          />
        </p>
      </template>
    </div>
  </AppAuthShell>
</template>

<script setup lang="ts">
import { useQuery, useQueryCache } from '@pinia/colada'
import { Ban, CircleCheck, Clock, Link2Off, ShieldAlert, UsersRound, WifiOff } from '@lucide/vue'
import { invitesAccept, invitesPreview, type InviteAcceptedSchema } from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { useApiClient } from '~/shared/api/useResource'
import { ensureSession, SESSION_KEY } from '~/shared/composables/useSession'
import AppAuthShell from '~/shared/components/layout/AppAuthShell.vue'
import InviteRegisterForm from '../components/invite/InviteRegisterForm.vue'
import { getRoleLabel } from '../composables/useOrganizationRole'
import { apiErrorReason, organizationErrorMessage } from '../composables/organizationErrors'

const route = useRoute()
const client = useApiClient()
const queryCache = useQueryCache()
const setupStore = useSetupStore()
const toast = useToast()
const { user, isSignedIn, organizations, logout, query: sessionQuery } = useSession()
// Public page: the session loads here, not in the route guard; wait for it instead of flashing the sign-up form.
const sessionPending = computed(() => sessionQuery.status.value === 'pending')
const { formatDate } = useDate()

const token = computed(() => String(route.params.token ?? ''))
const preview = useQuery({
  key: () => ['invite-preview', token.value],
  query: async ({ signal }) =>
    (await invitesPreview({ client, throwOnError: true, signal, path: { token: token.value } })).data,
  // Every lookup counts against the per-IP limit; refresh only on demand.
  staleTime: Infinity,
  refetchOnWindowFocus: false,
})
const invite = computed(() => preview.data.value ?? null)
const roleLabel = computed(() => getRoleLabel(invite.value?.role))
const expiresAt = computed(() => formatDate(invite.value?.expires_at ?? null, { disableRelative: true }))
const accountName = computed(
  () => `${user.value?.first_name ?? ''} ${user.value?.last_name ?? ''}`.trim() || user.value?.email || '',
)
const loginRoute = computed(() => ({ name: 'auth', query: { redirect: route.fullPath } }))

const loadError = computed(() => {
  const error = preview.error.value
  if (!error) return null
  if (isApiError(error, 404))
    return {
      icon: Link2Off,
      tone: 'muted' as const,
      title: 'Ссылка недействительна',
      description: 'Проверьте, что ссылка скопирована целиком, или попросите новую',
      retry: false,
    }
  if (isApiError(error, 429))
    return {
      icon: ShieldAlert,
      tone: 'warning' as const,
      title: 'Слишком много попыток',
      description: 'Подождите несколько минут и откройте ссылку снова',
      retry: true,
    }
  return {
    icon: WifiOff,
    tone: 'destructive' as const,
    title: 'Не удалось открыть приглашение',
    description: 'Проверьте соединение и попробуйте ещё раз',
    retry: true,
  }
})

const closedState = computed(() => {
  if (invite.value?.state === 'used') return { icon: CircleCheck, title: 'Приглашение уже использовано' }
  if (invite.value?.state === 'revoked') return { icon: Ban, title: 'Приглашение отозвано' }
  return { icon: Clock, title: 'Срок приглашения истёк' }
})

const alreadyMember = ref(false)

// The new membership must be in the session before the app restores the organization choice.
const enterOrganization = async (organization: { id: string; name: string; key: string }) => {
  await queryCache.invalidateQueries({ key: [...SESSION_KEY] })
  const session = await ensureSession()
  if (session && !setupStore.state.restored)
    await setupStore.restore({ userId: session.user.id, organizations: session.organizations })
  setupStore.state.organization = { id: organization.id, name: organization.name, key: organization.key }
  await navigateTo({ name: 'home' }, { replace: true })
}

const onAccepted = async (result: InviteAcceptedSchema) => {
  toast.default(`Добро пожаловать в «${result.organization.name}»`)
  await enterOrganization(result.organization)
}

const joinState = useActionState(async () => {
  try {
    const { data } = await invitesAccept({ client, throwOnError: true, path: { token: token.value } })
    await onAccepted(data)
  } catch (error) {
    const reason = apiErrorReason(error)
    if (reason === 'already_member') alreadyMember.value = true
    else if (reason?.startsWith('invite_')) await preview.refetch()
    else toast.error(organizationErrorMessage(error, 'Не удалось присоединиться. Попробуйте ещё раз'))
  }
})

const openApp = async () => {
  const match = organizations.value.filter((item) => item.name === invite.value?.organization_name)
  if (match.length === 1 && match[0]) await enterOrganization(match[0])
  else await navigateTo({ name: 'home' })
}

// Sign-out sends the app to /auth; come back here as a guest to register or sign in as someone else.
const switchAccount = async () => {
  const back = route.fullPath
  try {
    await logout.mutateAsync()
  } catch {
    toast.error('Не удалось выйти. Попробуйте ещё раз')
    return
  }
  await navigateTo(back, { replace: true })
}
</script>
