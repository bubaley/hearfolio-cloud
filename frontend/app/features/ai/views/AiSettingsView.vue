<template>
  <AppPageView
    title="AI и модели"
    description="Расшифровка, названия, теги и саммари идут через ваш ключ OpenRouter"
    content-class="px-4 pb-10"
  >
    <template #title-append>
      <span
        v-if="update.isLoading.value"
        class="text-xs text-muted-foreground"
        role="status"
        >Сохраняем…</span
      >
    </template>
    <div class="flex max-w-3xl flex-col gap-10 pt-2">
      <AppAlert
        v-if="!isAdmin"
        tone="info"
        title="Только для владельцев и администраторов"
        description="Модели и автоматизацию настраивают администраторы организации"
      />
      <AppAlert
        v-else-if="query.error.value && !draft"
        tone="destructive"
        :title="aiErrorMessage(query.error.value, 'Не удалось загрузить настройки AI')"
      >
        <AppTextButton
          label="Повторить"
          weight="medium"
          @click="query.refetch()"
        />
      </AppAlert>
      <div
        v-else-if="!draft"
        class="flex flex-col gap-6"
      >
        <AppSkeleton
          v-for="row in 4"
          :key="row"
          :lines="2"
          class="max-w-md"
        />
      </div>
      <template v-else>
        <AiConnectionSection :settings="draft" />

        <section aria-labelledby="ai-models-title">
          <h2
            id="ai-models-title"
            class="text-base font-semibold"
          >
            Модели
          </h2>
          <p class="mt-0.5 mb-2 text-sm text-muted-foreground">
            Участники выбирают из разрешённых моделей; модель по умолчанию используется автоматически
          </p>
          <AiModelPicker
            label="Расшифровка"
            description="Модели, которые принимают аудио"
            kind="audio"
            :configured="draft.has_api_key"
            :models="draft.transcription_models"
            :default-model="draft.transcription_default_model"
            @update:models="(models) => patch({ transcription_models: models })"
            @update:default="(model) => patch({ transcription_default_model: model })"
          />
          <AiModelPicker
            label="Названия, теги и саммари"
            description="Текстовые модели"
            kind="text"
            :configured="draft.has_api_key"
            :models="draft.summary_models"
            :default-model="draft.summary_default_model"
            @update:models="(models) => patch({ summary_models: models })"
            @update:default="(model) => patch({ summary_default_model: model })"
          />
        </section>

        <section aria-labelledby="ai-automation-title">
          <h2
            id="ai-automation-title"
            class="text-base font-semibold"
          >
            Автоматизация
          </h2>
          <p class="mt-0.5 mb-2 text-sm text-muted-foreground">Что происходит с новой записью без участия человека</p>
          <AppSettingRow
            v-for="toggle in toggles"
            :key="toggle.field"
            :label="toggle.label"
            :description="toggle.description"
            :for-id="`ai-${toggle.field}`"
          >
            <AppSwitch
              :id="`ai-${toggle.field}`"
              :model-value="draft[toggle.field]"
              size="lg"
              @update:model-value="(value: boolean) => patch({ [toggle.field]: value })"
            />
          </AppSettingRow>
        </section>

        <section aria-labelledby="ai-transcription-title">
          <h2
            id="ai-transcription-title"
            class="text-base font-semibold"
          >
            Расшифровка
          </h2>
          <AppSettingRow
            label="Длина фрагмента"
            description="Аудио режется на части такой длины. Короче — надёжнее, длиннее — быстрее"
          >
            <AppSelect
              :model-value="draft.segment_seconds"
              :options="segmentOptions"
              option-label="label"
              option-value="value"
              emit-value
              :filter="false"
              class="w-full sm:w-48"
              aria-label="Длина фрагмента"
              @update:model-value="(value: number | null) => value && patch({ segment_seconds: value })"
            />
          </AppSettingRow>
          <AppSettingRow
            label="Язык записей"
            description="Подсказка модели. «Автоматически» подходит для смешанной речи"
          >
            <AppSelect
              :model-value="draft.language"
              :options="languageOptions"
              option-label="label"
              option-value="value"
              emit-value
              class="w-full sm:w-48"
              aria-label="Язык записей"
              @update:model-value="(value: string | null) => value && patch({ language: value })"
            />
          </AppSettingRow>
        </section>
      </template>
    </div>
  </AppPageView>
</template>

<script setup lang="ts">
import type { OrganizationSettingsReadSchema } from '~/shared/api/generated'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import AiConnectionSection from '../components/ai-settings/AiConnectionSection.vue'
import AiModelPicker from '../components/ai-settings/AiModelPicker.vue'
import { aiErrorMessage, useAiSettings, type AiSettingsPatch } from '../composables/useAiSettings'

const { isAdmin } = useOrganizationRole()
const { settings, query, update } = useAiSettings({ enabled: () => isAdmin.value })
const toast = useToast()

// Shown values change at once; the server response (or a refetch on failure) settles them.
const draft = ref<OrganizationSettingsReadSchema | null>(null)
watch(
  settings,
  (value) => {
    if (value) draft.value = { ...value }
  },
  { immediate: true },
)

const patch = async (body: AiSettingsPatch) => {
  if (!draft.value) return
  draft.value = { ...draft.value, ...(body as Partial<OrganizationSettingsReadSchema>) }
  try {
    await update.mutateAsync(body)
  } catch (error) {
    toast.error(aiErrorMessage(error, 'Не удалось сохранить'))
    if (settings.value) draft.value = { ...settings.value }
  }
}

type ToggleField = 'auto_transcribe' | 'auto_title' | 'auto_tags' | 'auto_project'
const toggles: { field: ToggleField; label: string; description: string }[] = [
  {
    field: 'auto_transcribe',
    label: 'Расшифровывать сразу',
    description: 'Запускать расшифровку, как только запись загружена',
  },
  {
    field: 'auto_title',
    label: 'Придумывать название',
    description: 'Если название не меняли вручную',
  },
  { field: 'auto_tags', label: 'Расставлять теги', description: 'До 5 тегов, новые создаются при необходимости' },
  { field: 'auto_project', label: 'Предлагать проект', description: 'Запись не переносится без подтверждения' },
]

const segmentOptions = [60, 120, 180, 300, 600, 900].map((value) => ({
  value,
  label: `${value / 60} мин${value === 300 ? ' (рекомендуется)' : ''}`,
}))

const LANGUAGES: Record<string, string> = {
  auto: 'Автоматически',
  ru: 'Русский',
  en: 'Английский',
  uk: 'Украинский',
  kk: 'Казахский',
  be: 'Белорусский',
  de: 'Немецкий',
  fr: 'Французский',
  es: 'Испанский',
  it: 'Итальянский',
  tr: 'Турецкий',
  zh: 'Китайский',
  ja: 'Японский',
}
const languageOptions = computed(() => {
  const options = Object.entries(LANGUAGES).map(([value, label]) => ({ value, label }))
  const current = draft.value?.language
  return current && !LANGUAGES[current] ? [...options, { value: current, label: current }] : options
})
</script>
