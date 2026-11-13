<template>
  <AppModal
    v-model="open"
    title="Расшифровать заново"
    description="Текущий текст останется на месте, пока новая расшифровка не будет готова. Название обновится, если вы его не меняли"
    width="28rem"
  >
    <AppSelect
      v-model="model"
      label="Модель"
      :options="options?.transcription_models ?? []"
      :option-value="(item: string) => item"
      :option-label="(item: string) => item"
      :placeholder="options?.transcription_default_model ?? 'Модель по умолчанию'"
      :filter="false"
      emit-value
      :disabled="!options?.transcription_models.length"
      :hint="options?.transcription_models.length ? undefined : 'Администратор ещё не выбрал модели для расшифровки'"
    />
    <template #footer>
      <AppTemplateActions
        class="w-full sm:w-auto"
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          { label: 'Расшифровать', icon: AudioLines, action: submit },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { AudioLines } from '@lucide/vue'
import { useAiOptions } from '../../composables/useRecordingDetail'

const props = defineProps<{ submit: (model: string | null) => Promise<unknown> }>()
const open = defineModel<boolean>({ default: false })

const { data: options } = useAiOptions()
const model = ref<string | null>(null)

watch(open, (value) => {
  if (value) model.value = options.value?.transcription_default_model ?? null
})

const submit = async () => {
  try {
    await props.submit(model.value)
    open.value = false
  } catch {
    // The mutation already showed the error; keep the dialog open.
  }
}
</script>
