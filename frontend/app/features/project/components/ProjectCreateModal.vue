<template>
  <AppModal
    v-model="open"
    title="Новый проект"
    width="32rem"
  >
    <form
      class="flex flex-col gap-4"
      @submit.prevent="createState.execute"
    >
      <div class="flex items-end gap-2">
        <AppEmojiPicker
          v-model="form.emoji"
          label="Иконка проекта"
        />
        <AppInput
          v-model="form.name"
          label="Название"
          placeholder="Например, «Мобильное приложение»"
          maxlength="255"
          autofocus
          class="min-w-0 flex-1"
        />
      </div>
      <AppTextarea
        v-model="form.description"
        label="Описание"
        placeholder="О чём записи в этом проекте"
        :rows="2"
        auto-grow
        class="[&_textarea]:max-h-40"
      />
      <label class="flex items-start gap-3 text-sm">
        <AppSwitch
          v-model="form.is_private"
          class="mt-0.5"
        />
        <span>
          <span class="block font-medium">Приватный</span>
          <span class="text-muted-foreground">Проект и его записи видят только участники проекта</span>
        </span>
      </label>
      <div
        v-if="form.is_private"
        class="flex flex-col gap-1.5"
      >
        <span class="text-sm font-medium">Участники</span>
        <span class="text-xs text-muted-foreground">Вы станете участником автоматически</span>
        <ProjectMemberPicker
          v-model="memberIds"
          :exclude-ids="selfId ? [selfId] : []"
          empty-text="В организации пока нет других участников"
        />
      </div>
      <button
        type="submit"
        class="hidden"
        aria-hidden="true"
        tabindex="-1"
      />
    </form>
    <template #footer>
      <AppTemplateActions
        full-width
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          {
            label: 'Создать',
            loading: createState.loading.value,
            disabled: !form.name.trim(),
            action: createState.execute,
          },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { useResourceMutations } from '~/shared/api/useResource'
import { projectResource } from '../resources/project'
import { projectErrorMessage, useProjectActions } from '../composables/useProjects'
import ProjectMemberPicker from './ProjectMemberPicker.vue'

const open = defineModel<boolean>({ default: false })

const toast = useToast()
const { user } = useSession()
const selfId = computed(() => user.value?.id ?? null)
const { save } = useResourceMutations(projectResource)
const { addMember } = useProjectActions()

const form = ref(projectResource.toForm())
const memberIds = ref<string[]>([])
watch(open, (value) => {
  if (!value) return
  form.value = projectResource.toForm()
  memberIds.value = []
})

const createState = useActionState(async () => {
  if (!form.value.name.trim()) return
  let projectId: string
  try {
    const { item } = await save.mutateAsync(form.value)
    projectId = item.id
  } catch (error) {
    toast.error(projectErrorMessage(error, 'Не удалось создать проект'))
    throw error
  }
  if (form.value.is_private && memberIds.value.length) {
    const results = await Promise.allSettled(
      memberIds.value.map((userId) => addMember.mutateAsync({ id: projectId, userId })),
    )
    if (results.some((result) => result.status === 'rejected'))
      toast.error('Проект создан, но добавить удалось не всех участников')
  }
  toast.default('Проект создан')
  open.value = false
  await navigateTo({ name: 'projects-id', params: { id: projectId } })
})
</script>
