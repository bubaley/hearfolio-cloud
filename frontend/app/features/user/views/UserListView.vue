<template>
  <AppListTemplate
    title="Пользователи"
    description="Учётные записи этого сервера. Новых коллег удобнее звать ссылкой-приглашением в организацию"
    detail-route-name="settings-users-id"
    :resource="userResource"
    create-label="Новый пользователь"
    create-in-modal
    :detail-modal-props="{ title: 'Новый пользователь', width: '28rem' }"
    empty-text="Пользователей не нашлось"
  >
    <template #detail-modal="{ detailItem }">
      <AppInput
        v-model="detailItem.email"
        type="email"
        label="Электронная почта"
        autocomplete="off"
        autofocus
      />
      <div class="grid gap-4 sm:grid-cols-2">
        <AppInput
          v-model="detailItem.first_name"
          label="Имя"
        />
        <AppInput
          v-model="detailItem.last_name"
          label="Фамилия"
        />
      </div>
      <AppInput
        v-model="detailItem.password"
        type="password"
        label="Пароль"
        autocomplete="new-password"
      />
      <div class="flex items-center gap-2">
        <AppCheckbox
          v-model="detailItem.is_superuser"
          binary
          input-id="new-user-su"
        />
        <label
          for="new-user-su"
          class="text-sm"
          >Администратор сервера: создаёт пользователей и видит все организации</label
        >
      </div>
    </template>
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
