<template>
  <AppListTemplate
    title="Пользователи"
    description="Учётные записи этого сервера. Новых коллег удобнее звать ссылкой-приглашением в организацию"
    detail-route-name="settings-users-id"
    :resource="userResource"
    create-label="Новый пользователь"
    empty-text="Пользователей не нашлось"
  >
    <AppColumn header="Пользователь">
      <template #body="{ data }">
        <div class="flex min-w-0 items-center gap-3">
          <AppAvatar
            :name="userDisplayName(data)"
            variant="soft"
          />
          <div class="min-w-0">
            <div class="truncate text-sm font-medium">{{ userDisplayName(data) }}</div>
            <div
              v-if="userDisplayName(data) !== data.email"
              class="truncate text-sm text-muted-foreground"
            >
              {{ data.email }}
            </div>
          </div>
        </div>
      </template>
    </AppColumn>
    <AppColumn header="Доступ">
      <template #body="{ data }">
        <AppBadge
          v-if="data.is_superuser"
          label="Администратор сервера"
          tone="info"
          :icon="ShieldCheck"
        />
        <span
          v-else-if="data.is_active === false"
          class="text-sm text-muted-foreground"
          >Отключён</span
        >
        <span
          v-else
          class="text-sm text-muted-foreground"
          >Пользователь</span
        >
      </template>
    </AppColumn>
  </AppListTemplate>
</template>

<script setup lang="ts">
import { ShieldCheck } from '@lucide/vue'
import { userResource } from '../resources/user'
</script>
