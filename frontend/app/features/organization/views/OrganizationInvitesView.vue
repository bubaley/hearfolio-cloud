<template>
  <AppPageView
    title="Приглашения"
    description="Ссылка открывает регистрацию или вход и добавляет человека в организацию с выбранной ролью"
  >
    <template #actions>
      <AppButton
        :icon="Plus"
        label="Новое приглашение"
        @click="createOpen = true"
      />
    </template>
    <div class="flex flex-col">
      <section aria-label="Созданные ссылки">
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
        <div
          v-else
          class="flex justify-center py-10"
        >
          <div class="w-full max-w-sm">
            <AppResultState
              :icon="Link2"
              title="Приглашений пока нет"
              description="Создайте ссылку и отправьте её коллеге в любом мессенджере"
            >
              <template #actions>
                <AppButton
                  :icon="Plus"
                  label="Новое приглашение"
                  @click="createOpen = true"
                />
              </template>
            </AppResultState>
          </div>
        </div>
        <AppButton
          v-if="hasNextPage"
          variant="ghost"
          label="Показать ещё"
          :loading="isLoading"
          @click="loadNextPage()"
        />
      </section>
    </div>

    <InviteCreateModal v-model="createOpen" />
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
import { Link2, Plus } from '@lucide/vue'
import InviteCreateModal from '../components/invite-list/InviteCreateModal.vue'
import InviteRow from '../components/invite-list/InviteRow.vue'
import { organizationInviteResource, type OrganizationInvite } from '../resources/organizationInvite'
import { organizationErrorMessage } from '../composables/organizationErrors'

const client = useApiClient()
const queryCache = useQueryCache()
const toast = useToast()
const { items, isLoading, error, refetch, hasNextPage, loadNextPage } = useResourceList(organizationInviteResource)

// `?new=1` opens the modal at once (links from the empty «Все записи» screen).
const route = useRoute()
const createOpen = ref(route.query.new === '1')

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
