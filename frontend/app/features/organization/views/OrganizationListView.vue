<template>
  <AppListTemplate
    title="Организации"
    description="Команды, в которых вы состоите. В каждой свои записи, проекты и настройки AI"
    detail-route-name="settings-organizations-id"
    :resource="organizationResource"
    search-param="name"
    create-label="Новая организация"
    create-in-modal
    :detail-modal-props="{ title: 'Новая организация', width: '28rem' }"
    empty-text="Организаций не нашлось"
  >
    <template #detail-modal="{ detailItem }">
      <AppInput
        v-model="detailItem.name"
        label="Название"
        placeholder="Например, «Моя команда»"
        autofocus
      />
      <AppInput
        v-model="detailItem.key"
        label="Ключ"
        placeholder="my-team"
        hint="Латиница, цифры и дефис. Идентификатор для приложения и API, потом не меняется"
      />
    </template>
    <AppColumn header="Организация">
      <template #body="{ data }">
        <div class="flex min-w-0 items-center gap-3">
          <AppAvatar
            :name="data.name"
            variant="soft"
          />
          <span class="truncate text-sm font-medium">{{ data.name }}</span>
        </div>
      </template>
    </AppColumn>
    <AppColumn header="Ваша роль">
      <template #body="{ data }">
        <span class="text-sm text-muted-foreground">{{ roleOf(data.id) }}</span>
      </template>
    </AppColumn>
  </AppListTemplate>
</template>

<script setup lang="ts">
import { organizationResource } from '../resources/organization'
import { getRoleLabel } from '../composables/useOrganizationRole'

const { organizations, user } = useSession()

// Superusers also see organizations they are not members of.
const roleOf = (id: string) =>
  getRoleLabel(organizations.value.find((item) => item.id === id)?.role)?.label ??
  (user.value?.is_superuser ? 'Не участник' : '—')
</script>
