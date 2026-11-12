<template>
  <AppPageView
    title="Приглашения"
    description="Ссылка открывает регистрацию или вход и добавляет человека в организацию с выбранной ролью"
    content-class="px-4 pb-10"
  >
    <div class="flex max-w-3xl flex-col gap-8 pt-2">
      <InviteCreateForm />

      <section aria-labelledby="invite-list-title">
        <h2
          id="invite-list-title"
          class="mb-1 text-sm font-medium text-muted-foreground"
        >
          Созданные ссылки
        </h2>
        <AppAlert
          v-if="error && !items.length"
          tone="destructive"
          title="Не удалось загрузить приглашения"
        >
          <AppTextButton
            label="Повторить"
            weight="medium"
            @click="refetch()"
          />
        </AppAlert>
        <div
          v-else-if="isLoading && !items.length"
          class="flex flex-col gap-4 py-3"
        >
          <AppSkeleton
            v-for="row in 3"
            :key="row"
            :lines="2"
            class="max-w-sm"
          />
        </div>
        <ul v-else-if="items.length">
          <InviteRow
            v-for="invite in items"
            :key="invite.id"
            :invite="invite"
            @revoke="pendingRevoke = invite"
          />
        </ul>
        <p
          v-else
          class="py-6 text-sm text-muted-foreground"
        >
          Приглашений пока нет. Создайте ссылку и отправьте её коллеге в любом мессенджере
        </p>
        <AppButton
          v-if="hasNextPage"
          variant="ghost"
          label="Показать ещё"
          :loading="isLoading"
          @click="loadNextPage()"
        />
      </section>
    </div>

    <AppConfirmModal
      :model-value="Boolean(pendingRevoke)"
      title="Отозвать приглашение?"
      subtitle="Ссылка перестанет работать. Если ею ещё не воспользовались, создайте новую."
      confirm-text="Отозвать"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="revoke"
      @update:model-value="(open) => !open && (pendingRevoke = null)"
    />
  </AppPageView>
</template>

<script setup lang="ts">
import { useQueryCache } from '@pinia/colada'
import { organizationInvitesRevoke } from '~/shared/api/generated'
import { resourceKeys } from '~/shared/api/resource'
import { useApiClient, useResourceList } from '~/shared/api/useResource'
import InviteCreateForm from '../components/invite-list/InviteCreateForm.vue'
import InviteRow from '../components/invite-list/InviteRow.vue'
import { organizationInviteResource, type OrganizationInvite } from '../resources/organizationInvite'
import { organizationErrorMessage } from '../composables/organizationErrors'

const client = useApiClient()
const queryCache = useQueryCache()
const toast = useToast()
const { items, isLoading, error, refetch, hasNextPage, loadNextPage } = useResourceList(organizationInviteResource)

const pendingRevoke = ref<OrganizationInvite | null>(null)
const revoke = async () => {
  const invite = pendingRevoke.value
  if (!invite) return
  try {
    await organizationInvitesRevoke({ client, throwOnError: true, path: { item_id: invite.id } })
  } catch (reason) {
    toast.error(organizationErrorMessage(reason, 'Не удалось отозвать приглашение'))
    return
  } finally {
    await queryCache.invalidateQueries({ key: resourceKeys(organizationInviteResource).all })
  }
  pendingRevoke.value = null
  toast.default('Приглашение отозвано')
}
</script>
