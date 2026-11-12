<template>
  <AppModal
    v-model="open"
    :title="readonly ? form.name : form.id ? 'Шаблон саммари' : 'Новый шаблон'"
    :description="readonly ? 'Шаблоны настраивают администраторы организации' : undefined"
    width="40rem"
  >
    <form
      class="flex flex-col gap-4"
      @submit.prevent="saveState.execute"
    >
      <AppInput
        v-if="!readonly"
        v-model="form.name"
        label="Название"
        placeholder="Например, «Решения и задачи»"
        maxlength="100"
        autofocus
      />
      <AppTextarea
        v-model="form.prompt"
        label="Что должно быть в саммари"
        :readonly="readonly"
        :rows="8"
        auto-grow
        class="[&_textarea]:max-h-[50vh]"
        hint="Опишите формат и что выделить: решения, задачи, вопросы. Расшифровка подставится сама"
      />
      <label
        v-if="!readonly"
        class="flex items-start gap-3 text-sm"
      >
        <AppSwitch
          v-model="form.auto"
          class="mt-0.5"
        />
        <span>
          <span class="block font-medium">Создавать автоматически</span>
          <span class="text-muted-foreground">Для каждой новой записи сразу после расшифровки</span>
        </span>
      </label>
    </form>
    <template
      v-if="!readonly"
      #footer
    >
      <AppTemplateActions
        full-width
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          {
            label: form.id ? 'Сохранить' : 'Создать',
            loading: saveState.loading.value,
            disabled: !form.name.trim() || !form.prompt.trim(),
            action: saveState.execute,
          },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { useResourceMutations } from '~/shared/api/useResource'
import { summaryTemplateResource, type SummaryTemplate } from '../../resources/summaryTemplate'

const props = defineProps<{ template: SummaryTemplate | null; readonly?: boolean }>()
const open = defineModel<boolean>({ default: false })

const toast = useToast()
const { save } = useResourceMutations(summaryTemplateResource)
const form = ref(summaryTemplateResource.toForm())
watch(open, (value) => {
  if (value) form.value = summaryTemplateResource.toForm(props.template ?? undefined)
})

const saveState = useActionState(async () => {
  try {
    const { created } = await save.mutateAsync(form.value)
    toast.default(created ? 'Шаблон создан' : 'Шаблон сохранён')
  } catch (error) {
    toast.error(error instanceof Error && !('status' in error) ? error.message : 'Не удалось сохранить шаблон')
    throw error
  }
  open.value = false
})
</script>
