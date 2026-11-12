<template>
  <AppPageView
    title="Общие"
    description="Название организации и её удаление"
    content-class="px-4 pb-10"
  >
    <div class="flex max-w-3xl flex-col gap-8 pt-2">
      <section>
        <AppSettingRow
          label="Название"
          for-id="organization-name"
          :description="
            isAdmin ? 'Видно всем участникам и в приложении' : 'Изменить название могут владельцы и администраторы'
          "
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
              :readonly="!isAdmin"
              maxlength="255"
              autocomplete="off"
            />
            <AppButton
              v-if="isAdmin && dirty"
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
          description="Участники, приглашения, настройки AI и шаблоны будут удалены без возможности восстановления"
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
      title="Удалить организацию?"
      :subtitle="`«${organization?.name}» и все её данные будут удалены. Это действие нельзя отменить.`"
      confirm-text="Удалить навсегда"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="removeOrganization"
    />
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
const removeOrganization = async () => {
  const current = organization.value
  if (!current) return
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
