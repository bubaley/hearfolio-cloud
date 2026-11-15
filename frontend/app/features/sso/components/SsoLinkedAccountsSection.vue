<template>
  <AppSection
    title="Связанные аккаунты"
    description="Аккаунты провайдеров организаций (SSO), которыми вы входите в Hearfolio"
    title-size="md"
    class="gap-1"
  >
    <template #actions>
      <AppButton
        variant="outline"
        size="sm"
        label="Привязать"
        :icon="Link2"
        :disabled="!organizations.length"
        @click="linkOpen = true"
      />
    </template>
    <AppAlert
      v-if="callbackError"
      tone="destructive"
      title="Не удалось привязать аккаунт"
      :description="callbackError"
    />
    <AppSkeleton
      v-if="query.isLoading.value"
      :lines="2"
      class="max-w-md"
    />
    <p
      v-else-if="query.error.value"
      class="text-sm text-destructive"
    >
      Не удалось загрузить связанные аккаунты.
      <AppTextButton
        label="Повторить"
        weight="medium"
        @click="query.refetch()"
      />
    </p>
    <p
      v-else-if="!identities?.length"
      class="py-2 text-sm text-muted-foreground"
    >
      Пока нет. Привяжите аккаунт компании, чтобы входить без пароля
    </p>
    <AppSettingRow
      v-for="identity in identities ?? []"
      :key="identity.id"
      :label="identity.organization_name"
    >
      <template #description>
        {{ identity.email || identity.name || identity.issuer }}
        <template v-if="identity.last_login_at">
          · последний вход {{ lowerFirst(formatDate(identity.last_login_at)) }}</template
        >
      </template>
      <AppButton
        variant="ghost"
        text-variant="muted"
        label="Отвязать"
        :disabled="identity.is_only_sign_in"
        :title="identity.is_only_sign_in ? 'Это единственный способ входа в ваш аккаунт' : undefined"
        @click="unlinkTarget = identity"
      />
    </AppSettingRow>

    <AppModal
      v-model="linkOpen"
      title="Привязать аккаунт компании"
      description="Вы перейдёте к провайдеру организации и вернётесь сюда"
      width="28rem"
    >
      <AppSelect
        v-model="linkKey"
        label="Организация"
        :options="organizationOptions"
        option-label="label"
        option-value="value"
        emit-value
      />
      <p
        v-if="linkError"
        class="mt-3 text-sm text-destructive"
        role="alert"
      >
        {{ linkError }}
      </p>
      <template #footer>
        <AppTemplateActions
          full-width
          :actions="[
            { label: 'Отмена', variant: 'secondary', action: () => void (linkOpen = false) },
            {
              label: 'Перейти к провайдеру',
              icon: KeyRound,
              disabled: !linkKey,
              loading: linkState.loading.value,
              action: linkState.execute,
            },
          ]"
        />
      </template>
    </AppModal>

    <AppConfirmModal
      :model-value="Boolean(unlinkTarget)"
      title="Отвязать аккаунт?"
      :subtitle="`Входы через провайдера организации «${unlinkTarget?.organization_name ?? ''}» завершатся. Если организация открывается только через SSO, доступ к ней пропадёт до новой привязки.`"
      confirm-text="Отвязать"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="unlinkIdentity"
      @update:model-value="(value?: boolean) => !value && (unlinkTarget = null)"
    />
  </AppSection>
</template>

<script setup lang="ts">
import { KeyRound, Link2 } from '@lucide/vue'
import type { SsoIdentityReadSchema } from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { ssoCallbackErrorMessage, ssoErrorMessage, useSsoIdentities } from '../composables/useSso'

const route = useRoute()
const toast = useToast()
const { organizations } = useSession()
const { formatDate } = useDate()
const { identities, query, unlink, link } = useSsoIdentities()

const lowerFirst = (value: string | null) => (value ?? '').charAt(0).toLocaleLowerCase('ru') + (value ?? '').slice(1)
const callbackError = computed(() => ssoCallbackErrorMessage(route.query.sso_error))
const organizationOptions = computed(() => organizations.value.map((item) => ({ label: item.name, value: item.key })))

const linkOpen = ref(false)
const linkKey = ref<string | null>(null)
const linkError = ref('')
watch(linkOpen, (open) => {
  if (!open) return
  linkKey.value = organizationOptions.value[0]?.value ?? null
  linkError.value = ''
})
watch(linkKey, () => {
  linkError.value = ''
})
const linkState = useActionState(async () => {
  if (!linkKey.value) return
  try {
    await link(linkKey.value)
  } catch (error) {
    linkError.value = isApiError(error, 404)
      ? 'В этой организации вход через SSO не настроен'
      : ssoErrorMessage(error, 'Не удалось начать привязку')
  }
})

const unlinkTarget = ref<SsoIdentityReadSchema | null>(null)
const unlinkIdentity = async () => {
  const target = unlinkTarget.value
  if (!target) return
  try {
    await unlink.mutateAsync(target.id)
  } catch (error) {
    toast.error(ssoErrorMessage(error, 'Не удалось отвязать аккаунт'))
    return
  }
  unlinkTarget.value = null
  toast.default('Аккаунт отвязан')
}
</script>
