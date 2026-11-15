<template>
  <AppPageView
    title="Вход и участники"
    description="Вход через провайдера вашей компании (SSO) и правила, кто попадает в организацию"
  >
    <template
      v-if="isAdmin && settings?.provider"
      #actions
    >
      <AppButton
        variant="outline"
        label="Изменить подключение"
        :icon="Settings2"
        @click="modalOpen = true"
      />
    </template>
    <template #title-append>
      <span
        v-if="update.isLoading.value"
        class="text-xs text-muted-foreground"
        role="status"
        >Сохраняем…</span
      >
    </template>

    <div class="flex flex-col gap-10">
      <AppAlert
        v-if="!isAdmin"
        tone="info"
        title="Только для владельцев и администраторов"
        description="Вход и правила для участников настраивают администраторы организации"
      />
      <AppAlert
        v-else-if="query.error.value && !settings"
        tone="destructive"
        :title="ssoErrorMessage(query.error.value, 'Не удалось загрузить настройки входа')"
      >
        <AppTextButton
          label="Повторить"
          weight="medium"
          @click="query.refetch()"
        />
      </AppAlert>
      <div
        v-else-if="!settings"
        class="flex flex-col gap-6"
      >
        <AppSkeleton
          v-for="row in 3"
          :key="row"
          :lines="2"
          class="max-w-md"
        />
      </div>

      <AppResultState
        v-else-if="!settings.provider"
        :icon="KeyRound"
        title="Вход через SSO не подключён"
        description="Подключите провайдера OpenID Connect вашей компании: участники будут входить его аккаунтом, а вы — решать, кого пускать"
      >
        <template #actions>
          <div class="flex justify-center">
            <AppButton
              label="Подключить провайдера"
              :icon="Plus"
              @click="modalOpen = true"
            />
          </div>
        </template>
      </AppResultState>

      <template v-else>
        <section aria-labelledby="sso-provider-title">
          <h2
            id="sso-provider-title"
            class="text-base font-semibold"
          >
            Провайдер
          </h2>
          <p class="mt-0.5 mb-2 text-sm text-muted-foreground">
            Секрет хранится зашифрованным и не показывается после сохранения
          </p>
          <AppSettingRow label="Адрес (issuer)">
            <span class="text-sm break-all">{{ settings.provider.issuer }}</span>
          </AppSettingRow>
          <AppSettingRow label="Client id">
            <code class="rounded-md bg-muted px-2 py-1 font-mono text-sm break-all">{{
              settings.provider.client_id
            }}</code>
          </AppSettingRow>
          <AppSettingRow label="Scopes">
            <span class="text-sm break-words">{{ settings.provider.scopes.join(' ') }}</span>
          </AppSettingRow>
          <AppSettingRow label="Кнопка входа">
            <span class="text-sm">{{ settings.provider.button_label || 'Войти через SSO' }}</span>
          </AppSettingRow>
          <div class="flex flex-col gap-3 pt-3 sm:flex-row sm:items-center">
            <AppButton
              variant="outline"
              label="Проверить подключение"
              :icon="PlugZap"
              :loading="testState.loading.value"
              @click="testState.execute"
            />
            <p
              v-if="testSummary"
              class="flex min-w-0 items-start gap-1.5 text-sm"
              :class="testSummary.ok ? 'text-success' : 'text-destructive'"
              role="status"
            >
              <AppIcon
                :icon="testSummary.ok ? CircleCheck : CircleAlert"
                size="sm"
                class="mt-0.5 shrink-0"
              />
              <span>{{ testSummary.message }}</span>
            </p>
          </div>
        </section>

        <section aria-labelledby="sso-urls-title">
          <h2
            id="sso-urls-title"
            class="text-base font-semibold"
          >
            Адреса
          </h2>
          <AppSettingRow
            label="Адрес для возврата (redirect URI)"
            description="Зарегистрируйте у провайдера ровно этот адрес"
            stacked
          >
            <SsoCopyField
              :value="settings.redirect_uri"
              label="Адрес для возврата"
            />
          </AppSettingRow>
          <AppSettingRow
            label="Ссылка для входа"
            description="Отправьте её участникам: она ведёт сразу к входу через провайдера. Работает и для входа в приложение"
            stacked
          >
            <SsoCopyField
              :value="settings.login_url"
              label="Ссылка для входа"
            />
          </AppSettingRow>
        </section>

        <section aria-labelledby="sso-rules-title">
          <h2
            id="sso-rules-title"
            class="text-base font-semibold"
          >
            Правила
          </h2>
          <AppSettingRow
            label="Способ входа"
            description="«Только SSO»: организация открывается только после входа через провайдера"
          >
            <AppSelect
              :model-value="settings.provider.login_mode"
              :options="LOGIN_MODE_OPTIONS"
              option-label="label"
              option-value="value"
              emit-value
              class="w-full sm:w-64"
              aria-label="Способ входа"
              @update:model-value="(value: SsoLoginMode | null) => value && patch({ login_mode: value })"
            />
          </AppSettingRow>
          <AppSettingRow
            v-if="settings.provider.login_mode === 'sso_only'"
            label="Владельцы входят и по паролю"
            description="Запасной вход на случай, если провайдер сломается. Отключите, когда SSO проверен"
            for-id="sso-owner-fallback"
          >
            <AppSwitch
              id="sso-owner-fallback"
              :model-value="settings.provider.owner_password_fallback"
              size="lg"
              @update:model-value="(value: boolean) => patch({ owner_password_fallback: value })"
            />
          </AppSettingRow>
          <AppSettingRow
            label="Кто может войти"
            description="Новые люди из провайдера становятся участниками автоматически — или только по приглашению"
          >
            <AppSelect
              :model-value="settings.provider.join_policy"
              :options="JOIN_POLICY_OPTIONS"
              option-label="label"
              option-value="value"
              emit-value
              class="w-full sm:w-64"
              aria-label="Кто может войти"
              @update:model-value="(value: SsoJoinPolicy | null) => value && patch({ join_policy: value })"
            />
          </AppSettingRow>
          <AppSettingRow
            v-if="settings.provider.join_policy === 'provider'"
            label="Роль новых участников"
          >
            <AppSelect
              :model-value="settings.provider.default_role"
              :options="roleOptions"
              option-label="label"
              option-value="value"
              emit-value
              class="w-full sm:w-64"
              aria-label="Роль новых участников"
              @update:model-value="(value: OrganizationRole | null) => value && patch({ default_role: value })"
            />
          </AppSettingRow>
          <AppSettingRow
            label="Домены почты"
            description="Только подтверждённая почта этих доменов. Пусто — любой. Через пробел или запятую"
            for-id="sso-domains"
            stacked
          >
            <form
              class="flex w-full flex-col gap-2 sm:flex-row"
              @submit.prevent="saveList('allowed_email_domains', domains)"
            >
              <AppInput
                id="sso-domains"
                v-model="domains"
                class="min-w-0 flex-1"
                placeholder="company.ru"
                autocomplete="off"
              />
              <AppButton
                v-if="domainsDirty"
                type="submit"
                label="Сохранить"
              />
            </form>
          </AppSettingRow>
          <AppSettingRow
            label="Группы провайдера"
            description="Нужна хотя бы одна из этих групп (claim groups). Пусто — без ограничения"
            for-id="sso-groups"
            stacked
          >
            <form
              class="flex w-full flex-col gap-2 sm:flex-row"
              @submit.prevent="saveList('required_groups', groups)"
            >
              <AppInput
                id="sso-groups"
                v-model="groups"
                class="min-w-0 flex-1"
                placeholder="company:dev"
                autocomplete="off"
              />
              <AppButton
                v-if="groupsDirty"
                type="submit"
                label="Сохранить"
              />
            </form>
          </AppSettingRow>
          <AppSettingRow
            label="Проверка у провайдера"
            description="Как часто сеанс сверяется с провайдером: отключённый там человек теряет доступ не позже этого"
          >
            <AppSelect
              :model-value="settings.provider.revalidate_interval_minutes"
              :options="REVALIDATE_OPTIONS"
              option-label="label"
              option-value="value"
              emit-value
              class="w-full sm:w-64"
              aria-label="Проверка у провайдера"
              @update:model-value="(value: number | null) => value && patch({ revalidate_interval_minutes: value })"
            />
          </AppSettingRow>
        </section>

        <section aria-labelledby="sso-danger-title">
          <h2
            id="sso-danger-title"
            class="mb-1 text-sm font-medium text-muted-foreground"
          >
            Опасная зона
          </h2>
          <AppSettingRow
            label="Отключить провайдера"
            description="Сеансы через провайдера завершатся, привязки удалятся. Участники снова входят по паролю"
            tone="destructive"
          >
            <AppButton
              variant="outline"
              class="text-destructive"
              label="Отключить"
              :icon="Unplug"
              @click="confirmRemove = true"
            />
          </AppSettingRow>
        </section>
      </template>
    </div>

    <SsoProviderModal
      v-if="settings"
      v-model="modalOpen"
      :provider="settings.provider"
      :redirect-uri="settings.redirect_uri"
    />
    <AppConfirmModal
      v-model="confirmRemove"
      title="Отключить провайдера?"
      subtitle="Все входы через провайдера завершатся. Участники без пароля не смогут войти, пока им не зададут пароль."
      confirm-text="Отключить"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="removeProvider"
    />
  </AppPageView>
</template>

<script setup lang="ts">
import { CircleAlert, CircleCheck, KeyRound, PlugZap, Plus, Settings2, Unplug } from '@lucide/vue'
import type { OrganizationRole, SsoJoinPolicy, SsoLoginMode, SsoProviderUpdateSchema } from '~/shared/api/generated'
import { ROLE_LABELS, useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import SsoCopyField from '../components/SsoCopyField.vue'
import SsoProviderModal from '../components/SsoProviderModal.vue'
import {
  JOIN_POLICY_OPTIONS,
  LOGIN_MODE_OPTIONS,
  REVALIDATE_OPTIONS,
  splitList,
  ssoErrorMessage,
  useSsoSettings,
} from '../composables/useSso'

const { isAdmin } = useOrganizationRole()
const { settings, query, update, remove, testConnection } = useSsoSettings({ enabled: () => isAdmin.value })
const toast = useToast()
const modalOpen = ref(false)
const confirmRemove = ref(false)

const roleOptions = [
  { label: ROLE_LABELS.member.label, value: 'member' },
  { label: ROLE_LABELS.admin.label, value: 'admin' },
]

const patch = async (body: SsoProviderUpdateSchema) => {
  try {
    await update.mutateAsync(body)
  } catch (error) {
    toast.error(ssoErrorMessage(error, 'Не удалось сохранить'))
    // The select already shows the new value: put the saved one back.
    void query.refetch()
  }
}

const domains = ref('')
const groups = ref('')
watch(
  () => settings.value?.provider,
  (provider) => {
    domains.value = provider?.allowed_email_domains.join(', ') ?? ''
    groups.value = provider?.required_groups.join(', ') ?? ''
  },
  { immediate: true },
)
const sameList = (value: string, saved: string[] | undefined) => splitList(value).join(',') === (saved ?? []).join(',')
const domainsDirty = computed(
  () => !sameList(domains.value.toLowerCase(), settings.value?.provider?.allowed_email_domains),
)
const groupsDirty = computed(() => !sameList(groups.value, settings.value?.provider?.required_groups))
const saveList = (field: 'allowed_email_domains' | 'required_groups', value: string) =>
  patch({ [field]: splitList(field === 'allowed_email_domains' ? value.toLowerCase() : value) })

const testSummary = ref<{ ok: boolean; message: string } | null>(null)
const testState = useActionState(async () => {
  try {
    const result = await testConnection({})
    const failed = result.checks.find((check) => !check.ok)
    testSummary.value = failed
      ? { ok: false, message: `${failed.label}: ${failed.message}` }
      : { ok: true, message: 'Провайдер отвечает, ключи и client secret приняты' }
  } catch (error) {
    testSummary.value = { ok: false, message: ssoErrorMessage(error, 'Не удалось проверить подключение') }
  }
})

const removeProvider = async () => {
  try {
    await remove.mutateAsync()
  } catch (error) {
    toast.error(ssoErrorMessage(error, 'Не удалось отключить провайдера'))
    return
  }
  toast.default('Провайдер отключён')
}
</script>
