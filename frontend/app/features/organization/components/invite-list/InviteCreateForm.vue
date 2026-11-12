<template>
  <div class="flex flex-col gap-3">
    <form
      class="flex flex-col gap-2 sm:flex-row sm:items-end"
      @submit.prevent="createState.execute"
    >
      <AppSelect
        v-model="form.role"
        label="Роль"
        class="sm:w-48"
        :options="roleOptions"
        option-label="label"
        option-value="value"
        emit-value
        :filter="false"
      />
      <AppSelect
        v-model="form.expires_in_days"
        label="Действует"
        class="sm:w-36"
        :options="INVITE_EXPIRY_OPTIONS"
        option-label="label"
        option-value="value"
        emit-value
        :filter="false"
      />
      <AppButton
        type="submit"
        label="Создать ссылку"
        :icon="Link2"
        :loading="createState.loading.value"
      />
    </form>

    <AppCard
      v-if="created"
      tone="success"
      padding="sm"
      role="status"
    >
      <div class="flex flex-col gap-2">
        <div class="text-sm font-medium">Ссылка готова. Скопируйте её сейчас — позже её не показать</div>
        <div class="flex flex-col gap-2 sm:flex-row">
          <AppInput
            :model-value="created.url"
            readonly
            class="min-w-0 flex-1"
            aria-label="Ссылка-приглашение"
            @focus="($event.target as HTMLInputElement | null)?.select()"
          />
          <AppButton
            variant="outline"
            label="Копировать"
            :icon="Copy"
            @click="copy(created.url)"
          />
        </div>
        <div class="text-xs text-muted-foreground">
          Роль: {{ getRoleLabel(created.role)?.label.toLowerCase() }} · одна ссылка — один человек
        </div>
      </div>
    </AppCard>
  </div>
</template>

<script setup lang="ts">
import { Copy, Link2 } from '@lucide/vue'
import { useResourceMutations } from '~/shared/api/useResource'
import { organizationInviteResource, type CreatedInvite } from '../../resources/organizationInvite'
import { INVITE_EXPIRY_OPTIONS } from '../../composables/useInviteLabels'
import { ROLE_LABELS, getRoleLabel } from '../../composables/useOrganizationRole'
import { organizationErrorMessage } from '../../composables/organizationErrors'

const toast = useToast()
const { save } = useResourceMutations(organizationInviteResource)
const form = ref(organizationInviteResource.toForm())
const created = ref<CreatedInvite | null>(null)

const roleOptions = [
  { label: ROLE_LABELS.member.label, value: 'member' },
  { label: ROLE_LABELS.admin.label, value: 'admin' },
]

const copy = async (url: string) => {
  try {
    await navigator.clipboard.writeText(url)
    toast.default('Ссылка скопирована')
  } catch {
    toast.error('Не удалось скопировать. Выделите ссылку и скопируйте вручную')
  }
}

const createState = useActionState(async () => {
  try {
    const { item } = await save.mutateAsync(form.value)
    created.value = item as CreatedInvite
  } catch (error) {
    toast.error(organizationErrorMessage(error, 'Не удалось создать приглашение'))
    throw error
  }
  // The link is shown once: copy it right away when the browser allows it (some need a fresh click).
  try {
    await navigator.clipboard.writeText(created.value.url)
    toast.default('Ссылка создана и скопирована')
  } catch {
    toast.default('Ссылка создана', { description: 'Скопируйте её кнопкой «Копировать»' })
  }
})
</script>
