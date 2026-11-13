<template>
  <AppAuthShell>
    <AppResultState
      :icon="notFound ? FileQuestion : TriangleAlert"
      :tone="notFound ? 'muted' : 'warning'"
      :title="notFound ? 'Страница не найдена' : 'Что-то пошло не так'"
      :description="
        notFound
          ? 'Возможно, ссылка устарела или в адресе опечатка.'
          : 'Сервер не смог открыть эту страницу. Попробуйте обновить её через минуту.'
      "
    >
      <template #actions>
        <AppButton
          :icon="House"
          fluid
          @click="goHome"
        >
          На главную
        </AppButton>
        <AppButton
          v-if="!notFound"
          variant="secondary"
          :icon="RotateCw"
          fluid
          @click="reload"
        >
          Обновить страницу
        </AppButton>
      </template>
    </AppResultState>
    <template
      v-if="!notFound && error?.statusCode"
      #footer
      >Код ошибки: {{ error.statusCode }}</template
    >
  </AppAuthShell>
</template>

<script setup lang="ts">
import { FileQuestion, House, RotateCw, TriangleAlert } from '@lucide/vue'
import type { NuxtError } from '#app'
import AppAuthShell from '~/shared/components/layout/AppAuthShell.vue'

const props = defineProps<{ error: NuxtError | null }>()
const notFound = computed(() => props.error?.statusCode === 404)

const goHome = () => clearError({ redirect: '/' })
const reload = () => {
  if (import.meta.client) window.location.reload()
}

const { name } = useAppConfig()
useHead({ title: () => `${notFound.value ? 'Страница не найдена' : 'Ошибка'} · ${name}` })
useSeoMeta({ robots: 'noindex' })
</script>
