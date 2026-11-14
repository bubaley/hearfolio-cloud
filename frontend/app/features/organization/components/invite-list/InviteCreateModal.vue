<template>
  <AppModal
    v-model="open"
    :title="created ? 'Ссылка готова' : 'Новое приглашение'"
    :description="
      created
        ? 'Скопируйте её сейчас — позже её не показать'
        : 'Ссылка открывает регистрацию или вход и добавляет человека в организацию'
    "
    width="28rem"
  >
    <!-- Step 2: the link is shown once, right where it was created. -->
    <div
      v-if="created"
      class="flex flex-col gap-3"
      role="status"
    >
      <div class="flex gap-2">
        <AppInput
          :model-value="created.url"
          readonly
          class="min-w-0 flex-1"
          aria-label="Ссылка-приглашение"
          @focus="($event.target as HTMLInputElement | null)?.select()"
        />
        <AppButton
          variant="outline"
          :icon="copied ? Check : Copy"
          :label="copied ? 'Скопировано' : 'Копировать'"
          @click="copy(created.url)"
        />
      </div>
      <p class="text-sm text-muted-foreground">
        Роль: {{ getRoleLabel(created.role)?.label.toLowerCase() }} · одна ссылка — один человек
      </p>
    </div>
    <form
      v-else
      class="flex flex-col gap-4"
      @submit.prevent="createState.execute"
    >
      <AppSelect
        v-model="form.role"
        label="Роль"
        :options="roleOptions"
        option-label="label"
        option-value="value"
        emit-value
      />
      <AppSelect
        v-model="form.expires_in_days"
        label="Действует"
        :options="INVITE_EXPIRY_OPTIONS"
        option-label="label"
        option-value="value"
        emit-value
      />
    </form>
    <template #footer>
      <AppTemplateActions
        v-if="created"
        full-width
        :actions="[
          { label: 'Ещё одна ссылка', variant: 'secondary', action: () => void (created = null) },
          { label: 'Готово', action: () => void (open = false) },
        ]"
      />
      <AppTemplateActions
        v-else
        full-width
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          { label: 'Создать ссылку', icon: Link2, loading: createState.loading.value, action: createState.execute },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { Check, Copy, Link2 } from '@lucide/vue'
import { useResourceMutations } from '~/shared/api/useResource'
import { organizationInviteResource, type CreatedInvite } from '../../resources/organizationInvite'
import { INVITE_EXPIRY_OPTIONS } from '../../composables/useInviteLabels'
import { ROLE_LABELS, getRoleLabel } from '../../composables/useOrganizationRole'
import { organizationErrorMessage } from '../../composables/organizationErrors'

/**
 * «Новое приглашение»: like every other creation it is a modal. Role and lifetime first, then the link — it is
 * shown once, so the modal stays open with it until the user is done.
 */
const open = defineModel<boolean>({ default: false })

const toast = useToast()
const { save } = useResourceMutations(organizationInviteResource)
const form = ref(organizationInviteResource.toForm())
const created = ref<CreatedInvite | null>(null)
const copied = ref(false)
watch(open, (value) => {
  if (!value) return
  form.value = organizationInviteResource.toForm()
  created.value = null
  copied.value = false
})

const roleOptions = [
  { label: ROLE_LABELS.member.label, value: 'member' },
  { label: ROLE_LABELS.admin.label, value: 'admin' },
]

const copy = async (url: string) => {
  try {
    await navigator.clipboard.writeText(url)
    copied.value = true
    toast.default('Ссылка скопирована')
  } catch {
    toast.error('Не удалось скопировать. Выделите ссылку и скопируйте вручную')
  }
}

const createState = useActionState(async () => {
  copied.value = false
  try {
    const { item } = await save.mutateAsync(form.value)
    created.value = item as CreatedInvite
  } catch (error) {
    toast.error(organizationErrorMessage(error, 'Не удалось создать приглашение'))
    throw error
  }
  // Copy right away when the browser allows it (some need a fresh click).
  try {
    await navigator.clipboard.writeText(created.value.url)
    copied.value = true
    toast.default('Ссылка создана и скопирована')
  } catch {
    toast.default('Ссылка создана', { description: 'Скопируйте её кнопкой «Копировать»' })
  }
})
</script>
