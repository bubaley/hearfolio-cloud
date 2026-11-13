<template>
  <AppModal
    v-model="open"
    :title="organizationName ? `Добро пожаловать в «${organizationName}»` : 'Добро пожаловать'"
    description="Три шага, чтобы записи команды оказались здесь"
    width="30rem"
    @update:model-value="(value: boolean) => !value && dismiss()"
  >
    <ol class="flex flex-col gap-4">
      <li
        v-for="(step, index) in steps"
        :key="step.title"
        class="flex gap-3"
      >
        <span
          class="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground"
          aria-hidden="true"
          >{{ index + 1 }}</span
        >
        <div class="min-w-0 pt-0.5">
          <div class="text-sm font-medium">{{ step.title }}</div>
          <p class="text-sm text-muted-foreground">{{ step.text }}</p>
        </div>
      </li>
    </ol>
    <template #footer>
      <AppButton
        variant="secondary"
        :href="appDownloadUrl"
        external
        :icon="Download"
        label="Скачать приложение"
      />
      <AppButton
        label="Понятно"
        @click="dismiss"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { Download } from '@lucide/vue'
import { dismissWelcome, isWelcomePending } from '../composables/useWelcome'

const { appDownloadUrl } = useAppConfig()
const { user } = useSession()
const setupStore = useSetupStore()
const organizationName = computed(() => setupStore.state.organization?.name ?? '')

const steps = [
  {
    title: 'Установите приложение',
    text: 'Hearfolio для компьютера или Android записывает встречи, звонки и заметки.',
  },
  {
    title: 'Подключите устройство',
    text: 'В приложении откройте Настройки → Облако и укажите адрес этого сервера.',
  },
  { title: 'Записи появятся здесь', text: 'С расшифровкой, названием и саммари — для вас и коллег.' },
]

const open = ref(false)
watch(
  () => user.value?.id,
  (id) => {
    if (id && import.meta.client && isWelcomePending(id)) open.value = true
  },
  { immediate: true },
)

const dismiss = () => {
  if (user.value) dismissWelcome(user.value.id)
  open.value = false
}
</script>
