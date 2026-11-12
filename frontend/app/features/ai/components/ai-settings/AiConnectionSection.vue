<template>
  <section aria-labelledby="ai-connection-title">
    <h2
      id="ai-connection-title"
      class="text-base font-semibold"
    >
      Подключение
    </h2>
    <p class="mt-0.5 mb-2 text-sm text-muted-foreground">
      OpenRouter или любой совместимый с OpenAI API. Ключ хранится зашифрованным и не показывается после сохранения
    </p>
    <form
      class="flex flex-col"
      @submit.prevent="saveState.execute"
    >
      <AppSettingRow
        label="Адрес API"
        for-id="ai-base-url"
        stacked
      >
        <AppInput
          id="ai-base-url"
          v-model="baseUrl"
          type="url"
          class="w-full"
          placeholder="https://openrouter.ai/api/v1"
          autocomplete="off"
        />
      </AppSettingRow>
      <AppSettingRow
        label="Ключ API"
        for-id="ai-api-key"
        stacked
      >
        <template #description>
          <template v-if="settings.has_api_key">
            Сохранён ключ <code class="font-mono">••••{{ settings.api_key_hint }}</code
            >. Введите новый, чтобы заменить
          </template>
          <template v-else>Ключ ещё не задан — без него расшифровка и саммари не работают</template>
        </template>
        <div class="flex w-full flex-col gap-2 sm:flex-row">
          <AppInput
            id="ai-api-key"
            v-model="apiKey"
            type="password"
            class="min-w-0 flex-1"
            :placeholder="settings.has_api_key ? `••••${settings.api_key_hint ?? ''}` : 'sk-or-…'"
            autocomplete="new-password"
          />
          <AppButton
            v-if="settings.has_api_key && !apiKey"
            variant="ghost"
            text-variant="muted"
            label="Удалить ключ"
            :loading="removeKeyState.loading.value"
            @click="confirmRemoveKey = true"
          />
        </div>
      </AppSettingRow>

      <div class="flex flex-col gap-3 pt-3 sm:flex-row sm:items-center">
        <AppTemplateActions
          :actions="[
            {
              label: 'Сохранить',
              hidden: !dirty,
              loading: saveState.loading.value,
              disabled: !baseUrl.trim(),
              action: saveState.execute,
            },
            {
              label: 'Проверить подключение',
              variant: 'outline',
              icon: PlugZap,
              loading: testState.loading.value,
              disabled: !baseUrl.trim() || (!settings.has_api_key && !apiKey),
              action: testState.execute,
            },
          ]"
        />
        <p
          v-if="testResult"
          class="flex min-w-0 items-start gap-1.5 text-sm"
          :class="testResult.ok ? 'text-success' : 'text-destructive'"
          role="status"
        >
          <AppIcon
            :icon="testResult.ok ? CircleCheck : CircleAlert"
            size="sm"
            class="mt-0.5 shrink-0"
          />
          <span>{{ testResult.message }}</span>
        </p>
      </div>
    </form>

    <AppConfirmModal
      v-model="confirmRemoveKey"
      title="Удалить ключ API?"
      subtitle="Новые записи перестанут расшифровываться, пока вы не добавите ключ снова."
      confirm-text="Удалить"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="removeKeyState.execute"
    />
  </section>
</template>

<script setup lang="ts">
import { CircleAlert, CircleCheck, PlugZap } from '@lucide/vue'
import type { AiConnectionTestResultSchema, OrganizationSettingsReadSchema } from '~/shared/api/generated'
import { aiErrorMessage, useAiSettings } from '../../composables/useAiSettings'

const props = defineProps<{ settings: OrganizationSettingsReadSchema }>()

const toast = useToast()
const { update, testConnection } = useAiSettings()

const baseUrl = ref(props.settings.openrouter_base_url)
const apiKey = ref('')
watch(
  () => props.settings.openrouter_base_url,
  (value) => {
    baseUrl.value = value
  },
)
const dirty = computed(() => Boolean(apiKey.value) || baseUrl.value.trim() !== props.settings.openrouter_base_url)

// A check result describes the values it ran with; editing them makes it stale.
const testResult = ref<AiConnectionTestResultSchema | null>(null)
watch([baseUrl, apiKey], () => {
  testResult.value = null
})

const saveState = useActionState(
  async () => {
    try {
      await update.mutateAsync({
        openrouter_base_url: baseUrl.value.trim(),
        ...(apiKey.value ? { openrouter_api_key: apiKey.value.trim() } : {}),
      })
    } catch (error) {
      toast.error(aiErrorMessage(error, 'Не удалось сохранить подключение'))
      throw error
    }
    apiKey.value = ''
  },
  { successNotification: 'Подключение сохранено' },
)

// Checks what is on screen: unsaved values when edited, otherwise the saved key.
const testState = useActionState(async () => {
  try {
    testResult.value = await testConnection({
      openrouter_base_url: baseUrl.value.trim(),
      ...(apiKey.value ? { openrouter_api_key: apiKey.value.trim() } : {}),
    })
  } catch (error) {
    testResult.value = { ok: false, message: aiErrorMessage(error, 'Не удалось проверить подключение') }
  }
})

const confirmRemoveKey = ref(false)
const removeKeyState = useActionState(
  async () => {
    try {
      await update.mutateAsync({ openrouter_api_key: '' })
    } catch (error) {
      toast.error(aiErrorMessage(error, 'Не удалось удалить ключ'))
      throw error
    }
  },
  { successNotification: 'Ключ удалён' },
)
</script>
