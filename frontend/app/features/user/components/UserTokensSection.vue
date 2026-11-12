<template>
  <div class="flex flex-col gap-10">
    <UserDevicesList
      :devices="devices"
      :loading="isLoading"
    />
    <AppListTemplate
      title="Токены API"
      description="Для скриптов и интеграций. Полный токен показывается один раз, при создании"
      detail-mode="modal"
      template-variant="section"
      :detail-modal-props="{
        width: '32rem',
        closeOnSave: false,
        actionsProps: {
          disableRouterAutoResolving: true,
        },
      }"
      :items="tokens"
      only-client-search
      :build-new-item="() => userTokenResource.toForm({ user_id: props.userId })"
      :resource="userTokenResource"
      @save="onSave"
    >
      <AppColumn
        field="name"
        header="Наименование"
      />
      <AppColumn
        field="value_preview"
        header="Токен"
      />
      <AppColumn header="Последнее использование">
        <template #body="{ data }">
          <AppDateLabel
            v-if="data.last_used_at"
            :date="data.last_used_at"
          />
          <span
            v-else
            class="text-muted-foreground"
            >—</span
          >
        </template>
      </AppColumn>
      <AppColumn header="Создан">
        <template #body="{ data }">
          <AppDateLabel
            v-if="data.created_at"
            :date="data.created_at"
          />
        </template>
      </AppColumn>
      <template #detail-modal="{ detailItem }">
        <AppInput
          v-model="detailItem.name"
          label="Наименование"
        />
        <div v-if="detailItem.id">
          <AppCard
            :tone="detailItem.value ? 'success' : 'neutral'"
            class="w-full"
          >
            <div class="flex w-full items-start gap-2">
              <span class="min-w-0 flex-1 break-all whitespace-normal">
                {{ detailItem.value || detailItem.value_preview }}
              </span>
              <AppButton
                v-if="detailItem.value"
                variant="ghost"
                class="ml-4 shrink-0 text-success"
                :icon="Copy"
                aria-label="Скопировать токен"
                @click="copyToken(detailItem.value)"
              />
            </div>
          </AppCard>
        </div>
        <AppCard v-else>
          После сохранения полный токен будет показан в уведомлении. Сохраните его в надёжном месте.
        </AppCard>
      </template>
    </AppListTemplate>
  </div>
</template>

<script setup lang="ts">
import { Copy } from '@lucide/vue'
import { useResourceList } from '~/shared/api/useResource'
import UserDevicesList from './UserDevicesList.vue'
import { isDeviceToken, userTokenResource, type UserToken, type UserTokenForm } from '../resources/userToken'

const props = defineProps<{
  userId: string
}>()

const toast = useToast()

// One list for both sections: app devices (OAuth tokens) and hand-made API tokens. Writes through the resource
// invalidate it, so both refresh together.
const { items, isLoading } = useResourceList(userTokenResource, {
  params: () => ({ user_id: props.userId }),
  pageSize: 100,
})
const devices = computed(() => items.value.filter(isDeviceToken))
const tokens = computed(() => items.value.filter((token) => !isDeviceToken(token)))

// The full secret is in the create response only; the modal stays open to show it, the toast keeps a copy.
const onSave = (event: AppDetailActionsSaveResult<UserTokenForm, UserToken>) => {
  if (event.created && event.saved?.value) {
    toast.default('Токен создан', { description: event.saved.value, duration: 120_000 })
  }
}

const copyToken = async (value: string) => {
  try {
    await navigator.clipboard.writeText(value)
    toast.default('Скопировано')
  } catch {
    toast.error('Не удалось скопировать')
  }
}
</script>
