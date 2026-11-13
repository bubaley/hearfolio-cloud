<template>
  <AppModal
    v-model="open"
    title="Новый тег"
    width="28rem"
  >
    <form
      class="flex flex-col gap-4"
      @submit.prevent="createState.execute"
    >
      <div class="flex items-end gap-2">
        <AppInput
          v-model="name"
          label="Название"
          placeholder="Например, «Найм»"
          maxlength="64"
          autofocus
          class="min-w-0 flex-1"
        />
        <TagColorPicker v-model="color" />
      </div>
      <div class="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
        <span>Так он будет выглядеть:</span>
        <TagChip
          :name="name.trim() || 'Тег'"
          :color="color"
          class="max-w-48"
        />
      </div>
    </form>
    <template #footer>
      <AppTemplateActions
        full-width
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          {
            label: 'Создать',
            loading: createState.loading.value,
            disabled: !name.trim(),
            action: createState.execute,
          },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { useResourceMutations } from '~/shared/api/useResource'
import { tagResource, type TagColor } from '../resources/tag'
import { tagErrorMessage } from '../composables/tagColors'
import TagChip from './TagChip.vue'
import TagColorPicker from './TagColorPicker.vue'

/** «Новый тег»: a name and an optional color (without one the server picks it). */
const open = defineModel<boolean>({ default: false })

const toast = useToast()
const { save } = useResourceMutations(tagResource)
const name = ref('')
const color = ref<TagColor | null>(null)
watch(open, (value) => {
  if (!value) return
  name.value = ''
  color.value = null
})

const createState = useActionState(async () => {
  if (!name.value.trim()) return
  try {
    await save.mutateAsync({ id: null, name: name.value, color: color.value })
  } catch (reason) {
    toast.error(tagErrorMessage(reason, 'Не удалось создать тег'))
    throw reason
  }
  toast.default('Тег создан')
  open.value = false
})
</script>
