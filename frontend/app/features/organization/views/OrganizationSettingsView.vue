<template>
  <AppPageView
    title="Общие"
    :description="isOwner ? 'Название организации и её удаление' : 'Сведения об организации'"
    content-class="px-4 pb-10"
  >
    <div class="flex flex-col gap-8 pt-2">
      <section>
        <AppSettingRow
          v-if="!isAdmin"
          label="Название"
          description="Изменить название могут владельцы и администраторы"
        >
          <span class="text-sm font-medium break-words">{{ organization?.name }}</span>
        </AppSettingRow>
        <AppSettingRow
          v-else
          label="Название"
          for-id="organization-name"
          description="Видно всем участникам и в приложении"
          stacked
        >
          <form
            class="flex w-full flex-col gap-2 sm:flex-row"
            @submit.prevent="renameState.execute"
          >
            <AppInput
              id="organization-name"
              v-model="name"
              class="min-w-0 flex-1"
              maxlength="255"
              autocomplete="off"
            />
            <AppButton
              v-if="dirty"
              type="submit"
              label="Сохранить"
              :loading="renameState.loading.value"
              :disabled="!name.trim()"
            />
          </form>
        </AppSettingRow>
        <AppSettingRow
          label="Ключ"
          description="Идентификатор организации для приложения и API. Не меняется"
        >
          <code class="rounded-md bg-muted px-2 py-1 font-mono text-sm break-all">{{ organization?.key }}</code>
        </AppSettingRow>
        <AppSettingRow label="Ваша роль">
          <AppBadge
            v-if="roleLabel"
            :icon="roleLabel.icon"
            :tone="roleLabel.tone"
            :label="roleLabel.label"
          />
          <span
            v-else-if="isSuperuser"
            class="text-sm text-muted-foreground"
            >Администратор сервера</span
          >
        </AppSettingRow>
      </section>

      <section
        v-if="isOwner"
        aria-labelledby="danger-zone"
      >
        <h2
          id="danger-zone"
          class="mb-1 text-sm font-medium text-muted-foreground"
        >
          Опасная зона
        </h2>
        <AppSettingRow
          label="Удалить организацию"
          description="Все записи с аудио, расшифровками и саммари, проекты, теги, участники и настройки удаляются навсегда"
          tone="destructive"
        >
          <AppButton
            variant="outline"
            class="text-destructive"
            label="Удалить"
            :icon="Trash2"
            @click="confirmDelete = true"
          />
        </AppSettingRow>
      </section>
    </div>

    <AppConfirmModal
      v-model="confirmDelete"
      width="28rem"
      title="Удалить организацию?"
      hide-subtitle
      confirm-text="Удалить навсегда"
      :confirm-props="{ variant: 'destructive', disabled: !nameConfirmed }"
      :confirm="removeOrganization"
    >
      <div class="flex flex-col gap-4 text-sm">
        <p class="text-muted-foreground">
          Вместе с «<span class="font-medium text-foreground">{{ organization?.name }}</span
          >» будут удалены:
        </p>
        <ul class="flex list-disc flex-col gap-1 pl-5 text-muted-foreground">
          <li>
            <span class="text-foreground">все записи организации и их аудиофайлы</span> — у всех участников, включая
            личные записи и записи приватных проектов;
          </li>
          <li>расшифровки, саммари и публичные ссылки на записи;</li>
          <li>проекты, теги, шаблоны, приглашения, участники и настройки AI.</li>
        </ul>
        <p class="font-medium text-destructive">Восстановить их будет нельзя.</p>
        <AppInput
          id="organization-delete-confirm"
          v-model="confirmName"
          :label="`Чтобы подтвердить, введите название: ${organization?.name ?? ''}`"
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          @keydown.enter.prevent="nameConfirmed && confirmButtonClick()"
        />
      </div>
    </AppConfirmModal>
  </AppPageView>
</template>

<script setup lang="ts">
import { Trash2 } from '@lucide/vue'
import { useResourceMutations } from '~/shared/api/useResource'
import { organizationResource } from '../resources/organization'
import { getRoleLabel, useOrganizationRole } from '../composables/useOrganizationRole'
import { organizationErrorMessage } from '../composables/organizationErrors'

const setupStore = useSetupStore()
const { organizations } = useSession()
const { role, isAdmin, isOwner, isSuperuser } = useOrganizationRole()
const { save, remove } = useResourceMutations(organizationResource)
const toast = useToast()

const organization = computed(() => {
  const selected = setupStore.state.organization
  return organizations.value.find((item) => item.id === selected?.id) ?? selected
})
const roleLabel = computed(() => getRoleLabel(role.value))

const name = ref('')
watch(
  () => organization.value?.name,
  (value) => {
    name.value = value ?? ''
  },
  { immediate: true },
)
const dirty = computed(() => name.value.trim() !== (organization.value?.name ?? ''))

const renameState = useActionState(
  async () => {
    const current = organization.value
    if (!current || !name.value.trim()) return
    try {
      const { item } = await save.mutateAsync({ id: current.id, name: name.value.trim(), key: current.key })
      setupStore.state.organization = { id: item.id, name: item.name, key: item.key }
    } catch (error) {
      toast.error(organizationErrorMessage(error, 'Не удалось переименовать организацию'))
      throw error
    }
  },
  { successNotification: 'Название сохранено' },
)

const confirmDelete = ref(false)
const confirmName = ref('')
watch(confirmDelete, (open) => {
  if (open) confirmName.value = ''
})
// Typing the name is the guard against deleting the wrong organization; case and outer spaces do not matter.
const nameConfirmed = computed(
  () =>
    Boolean(organization.value?.name) &&
    confirmName.value.trim().toLocaleLowerCase('ru') === organization.value!.name.trim().toLocaleLowerCase('ru'),
)
const confirmButtonClick = () => {
  void removeOrganization().then(() => {
    confirmDelete.value = false
  })
}

const removeOrganization = async () => {
  const current = organization.value
  if (!current || !nameConfirmed.value) return
  try {
    await remove.mutateAsync(current.id)
  } catch (error) {
    toast.error(organizationErrorMessage(error, 'Не удалось удалить организацию'))
    return
  }
  setupStore.state.organization = null
  toast.default(`Организация «${current.name}» удалена`)
  await navigateTo({ name: 'home-setup' }, { replace: true })
}
</script>
