<template>
  <AppSection
    title="Подключённые устройства"
    description="Приложения Hearfolio, которые вошли через браузер. Отключите устройство, если потеряли его или больше не пользуетесь"
    template-variant="section"
    title-size="md"
  >
    <div
      v-if="loading && !devices.length"
      class="flex flex-col gap-4"
    >
      <AppSkeleton
        v-for="row in 2"
        :key="row"
        :lines="2"
        class="max-w-sm"
      />
    </div>
    <ul
      v-else-if="devices.length"
      class="max-w-3xl"
    >
      <li
        v-for="device in devices"
        :key="device.id"
        class="flex min-h-14 items-center gap-3 border-b border-border py-2 last:border-b-0"
      >
        <span class="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
          <AppIcon
            :icon="MonitorSmartphone"
            size="sm"
          />
        </span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-medium">{{ deviceName(device) }}</div>
          <div class="text-sm text-muted-foreground">
            Подключено {{ formatDate(parseDate(device.created_at), { type: 'date', disableRelative: true }) }} ·
            {{
              device.last_used_at
                ? `активность ${formatDate(device.last_used_at, { disableRelative: true })}`
                : 'ещё не использовалось'
            }}
          </div>
        </div>
        <AppButton
          variant="ghost"
          size="sm"
          text-variant="muted"
          class="h-11 md:h-control-sm"
          label="Отключить"
          @click="pending = device"
        />
      </li>
    </ul>
    <p
      v-else
      class="text-sm text-muted-foreground"
    >
      Нет подключённых устройств. Войдите в приложении Hearfolio, указав адрес этого сервера
    </p>

    <AppConfirmModal
      :model-value="Boolean(pending)"
      title="Отключить устройство?"
      :subtitle="`Hearfolio на «${pending ? deviceName(pending) : ''}» выйдет из учётной записи и перестанет загружать записи.`"
      confirm-text="Отключить"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="disconnect"
      @update:model-value="(open) => !open && (pending = null)"
    />
  </AppSection>
</template>

<script setup lang="ts">
import { MonitorSmartphone } from '@lucide/vue'
import { useResourceMutations } from '~/shared/api/useResource'
import { DEVICE_TOKEN_PREFIX, userTokenResource, type UserToken } from '../resources/userToken'

defineProps<{ devices: UserToken[]; loading?: boolean }>()

const toast = useToast()
// Instants: parse as datetime (local zone) and show the day only.
const { formatDate, parseDate } = useDate()
const { remove } = useResourceMutations(userTokenResource)
const deviceName = (token: UserToken) => token.name.slice(DEVICE_TOKEN_PREFIX.length).trim() || token.name

const pending = ref<UserToken | null>(null)
const disconnect = async () => {
  const device = pending.value
  if (!device) return
  try {
    await remove.mutateAsync(device.id)
  } catch (error) {
    toast.error('Не удалось отключить устройство')
    return
  }
  pending.value = null
  toast.default('Устройство отключено')
}
</script>
