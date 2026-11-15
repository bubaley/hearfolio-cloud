<template>
  <AppModal
    v-model="open"
    :title="provider ? 'Подключение провайдера' : 'Подключить провайдера'"
    description="Любой провайдер OpenID Connect: корпоративный SSO, Keycloak, Google, Okta и другие"
    width="36rem"
  >
    <form
      class="flex flex-col gap-4"
      @submit.prevent="saveState.execute"
    >
      <div class="flex flex-col gap-1.5">
        <span class="text-sm font-medium">Адрес для возврата (redirect URI)</span>
        <SsoCopyField
          :value="redirectUri"
          label="Адрес для возврата"
        />
        <p class="text-xs text-muted-foreground">
          Зарегистрируйте приложение у провайдера с этим адресом, затем перенесите сюда client id и client secret
        </p>
      </div>
      <AppInput
        id="sso-issuer"
        v-model="form.issuer"
        label="Адрес провайдера (issuer)"
        type="url"
        placeholder="https://id.company.ru"
        autocomplete="off"
        required
      />
      <AppInput
        id="sso-client-id"
        v-model="form.clientId"
        label="Client id"
        autocomplete="off"
        required
      />
      <AppInput
        id="sso-client-secret"
        v-model="form.clientSecret"
        label="Client secret"
        type="password"
        autocomplete="new-password"
        :placeholder="provider?.has_client_secret ? 'Сохранён. Введите новый, чтобы заменить' : ''"
        :required="!provider"
      />
      <AppInput
        id="sso-scopes"
        v-model="form.scopes"
        label="Scopes"
        autocomplete="off"
        placeholder="openid email profile groups offline_access"
      />
      <AppInput
        id="sso-button-label"
        v-model="form.buttonLabel"
        label="Подпись кнопки входа"
        placeholder="Войти через SSO"
        maxlength="64"
        autocomplete="off"
      />
      <p
        v-if="secretRequired"
        class="text-sm text-warning"
      >
        Адрес или client id изменились — укажите client secret заново
      </p>

      <div
        v-if="testResult"
        class="flex flex-col gap-1.5 rounded-md border border-border p-3 text-sm"
        role="status"
      >
        <p
          v-for="check in testResult.checks"
          :key="check.label"
          class="flex items-start gap-1.5"
          :class="check.ok ? 'text-success' : 'text-destructive'"
        >
          <AppIcon
            :icon="check.ok ? CircleCheck : CircleAlert"
            size="sm"
            class="mt-0.5 shrink-0"
          />
          <span>
            <span class="font-medium">{{ `${check.label}: ` }}</span>
            <span class="text-foreground">{{ check.message }}</span>
          </span>
        </p>
        <p
          v-if="testResult.unsupported_scopes.length"
          class="text-muted-foreground"
        >
          Провайдер не объявляет scopes: {{ testResult.unsupported_scopes.join(', ') }}. Если вход не заработает —
          уберите их
        </p>
      </div>
    </form>
    <template #footer>
      <AppTemplateActions
        full-width
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          {
            label: 'Проверить',
            variant: 'outline',
            icon: PlugZap,
            loading: testState.loading.value,
            disabled: !form.issuer.trim(),
            action: testState.execute,
          },
          {
            label: provider ? 'Сохранить' : 'Подключить',
            loading: saveState.loading.value,
            disabled: !canSave,
            action: saveState.execute,
          },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { CircleAlert, CircleCheck, PlugZap } from '@lucide/vue'
import type { SsoConnectionTestResultSchema, SsoProviderReadSchema } from '~/shared/api/generated'
import { splitList, ssoErrorMessage, useSsoSettings } from '../composables/useSso'
import SsoCopyField from './SsoCopyField.vue'

/** Connect or change the organization's provider. Discovery is checked by the server on save. */
const props = defineProps<{ provider: SsoProviderReadSchema | null; redirectUri: string }>()
const open = defineModel<boolean>({ default: false })

const DEFAULT_SCOPES = 'openid email profile groups offline_access'
const toast = useToast()
const { update, testConnection } = useSsoSettings()

const blank = () => ({
  issuer: props.provider?.issuer ?? '',
  clientId: props.provider?.client_id ?? '',
  clientSecret: '',
  scopes: props.provider?.scopes.join(' ') ?? DEFAULT_SCOPES,
  buttonLabel: props.provider?.button_label ?? '',
})
const form = ref(blank())
const testResult = ref<SsoConnectionTestResultSchema | null>(null)
watch(open, (value) => {
  if (!value) return
  form.value = blank()
  testResult.value = null
})
watch(
  () => [form.value.issuer, form.value.clientId, form.value.clientSecret, form.value.scopes],
  () => {
    testResult.value = null
  },
)

const secretRequired = computed(
  () =>
    Boolean(props.provider) &&
    !form.value.clientSecret &&
    (form.value.issuer.trim().replace(/\/$/, '') !== props.provider!.issuer.replace(/\/$/, '') ||
      form.value.clientId.trim() !== props.provider!.client_id),
)
const canSave = computed(
  () =>
    Boolean(form.value.issuer.trim() && form.value.clientId.trim()) &&
    (props.provider ? !secretRequired.value : Boolean(form.value.clientSecret)),
)

const connectionBody = () => {
  const issuerChanged = !props.provider || form.value.issuer.trim() !== props.provider.issuer
  return {
    ...(issuerChanged ? { issuer: form.value.issuer.trim() } : {}),
    client_id: form.value.clientId.trim(),
    ...(form.value.clientSecret ? { client_secret: form.value.clientSecret } : {}),
    scopes: splitList(form.value.scopes),
  }
}

const testState = useActionState(async () => {
  try {
    testResult.value = await testConnection({ issuer: form.value.issuer.trim(), ...connectionBody() })
  } catch (error) {
    testResult.value = {
      ok: false,
      checks: [{ label: 'Проверка', ok: false, message: ssoErrorMessage(error, 'Не удалось проверить подключение') }],
      unsupported_scopes: [],
    }
  }
})

const saveState = useActionState(
  async () => {
    if (!canSave.value) return
    try {
      await update.mutateAsync({ ...connectionBody(), button_label: form.value.buttonLabel.trim() })
    } catch (error) {
      toast.error(ssoErrorMessage(error, 'Не удалось сохранить подключение'))
      throw error
    }
    open.value = false
  },
  { successNotification: props.provider ? 'Подключение сохранено' : 'Провайдер подключён' },
)
</script>
