<template>
  <AppModal
    v-model="open"
    title="Создать саммари"
    description="Каждый шаблон станет отдельным саммари. Можно добавить свой запрос"
    width="32rem"
  >
    <div class="flex flex-col gap-5">
      <AppAlert
        v-if="notConfigured"
        tone="warning"
        title="AI ещё не настроен"
        :description="
          isAdmin
            ? 'Добавьте ключ OpenRouter в настройках организации — без него саммари не создать'
            : 'Попросите администратора добавить ключ OpenRouter в настройках организации'
        "
      >
        <AppTextButton
          v-if="isAdmin"
          label="Открыть «AI и модели»"
          weight="medium"
          :to="{ name: 'settings-ai' }"
        />
      </AppAlert>

      <fieldset class="flex flex-col gap-1">
        <legend class="mb-1.5 text-sm font-medium">Шаблоны</legend>
        <div
          v-if="templatesLoading && !templates.length"
          class="flex flex-col gap-2"
        >
          <AppSkeleton
            v-for="row in 3"
            :key="row"
            class="h-5 w-1/2"
          />
        </div>
        <p
          v-else-if="!templates.length"
          class="text-sm text-muted-foreground"
        >
          В организации пока нет шаблонов — напишите свой запрос ниже
        </p>
        <label
          v-for="template in templates"
          :key="template.id"
          class="flex min-h-10 cursor-pointer items-start gap-3 rounded-md px-2 py-2 hover:bg-field-hover max-md:min-h-11"
        >
          <AppCheckbox
            v-model="templateIds"
            :val="template.id"
            class="mt-0.5"
          />
          <span class="flex min-w-0 flex-col gap-0.5">
            <span class="text-sm">{{ template.name }}</span>
            <span class="line-clamp-2 text-xs text-muted-foreground">{{ templateDescription(template) }}</span>
          </span>
        </label>
      </fieldset>

      <AppTextarea
        v-model="customPrompt"
        label="Свой запрос"
        placeholder="Например: выпиши все даты и сроки, о которых договорились"
        :rows="3"
        auto-grow
      />

      <AppSelect
        v-model="model"
        label="Модель"
        :options="options?.summary_models ?? []"
        :option-value="(item: string) => item"
        :option-label="(item: string) => item"
        :placeholder="options?.summary_default_model ?? 'Модель по умолчанию'"
        emit-value
        :disabled="!options?.summary_models.length"
        :hint="options?.summary_models.length ? undefined : 'Администратор ещё не выбрал модели для саммари'"
      />
      <p
        v-if="formError"
        role="alert"
        class="text-sm text-destructive"
      >
        {{ formError }}
      </p>
    </div>
    <template #footer>
      <AppTemplateActions
        class="w-full sm:w-auto"
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          {
            label: count > 1 ? `Создать ${count}` : 'Создать',
            icon: Sparkles,
            disabled: !count || notConfigured,
            action: submit,
          },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { Sparkles } from '@lucide/vue'
import type { RecordingResultsCreateSchema } from '~/shared/api/generated'
import { useResourceList } from '~/shared/api/useResource'
import { summaryTemplateResource, type SummaryTemplate } from '~/features/ai/resources/summaryTemplate'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import { useAiOptions, type useRecordingResults } from '../../composables/useRecordingDetail'
import { recordingErrorMessage } from '../../composables/useRecordingMutations'
import { templateDescription } from '~/features/ai/resources/summaryTemplate'

const props = defineProps<{ create: ReturnType<typeof useRecordingResults>['create'] }>()
const open = defineModel<boolean>({ default: false })

const toast = useToast()
const { isAdmin } = useOrganizationRole()
const { data: options } = useAiOptions()
const { items: templates, isLoading: templatesLoading } = useResourceList<SummaryTemplate>(summaryTemplateResource, {
  enabled: open,
})

const templateIds = ref<string[]>([])
const customPrompt = ref('')
const model = ref<string | null>(null)
const formError = ref('')

const notConfigured = computed(() => options.value?.configured === false)
const count = computed(() => templateIds.value.length + (customPrompt.value.trim() ? 1 : 0))

watch(open, (value) => {
  if (!value) return
  templateIds.value = []
  customPrompt.value = ''
  formError.value = ''
  model.value = options.value?.summary_default_model ?? null
})

const submit = async () => {
  formError.value = ''
  const body: RecordingResultsCreateSchema = {
    template_ids: templateIds.value,
    custom_prompt: customPrompt.value.trim() || null,
    model: model.value,
  }
  try {
    const created = await props.create.mutateAsync(body)
    open.value = false
    toast.default(created.length > 1 ? `Создаём саммари: ${created.length}` : 'Создаём саммари')
  } catch (error) {
    formError.value = recordingErrorMessage(error, 'Не удалось создать саммари')
  }
}
</script>
