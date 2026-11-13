<template>
  <div class="flex min-h-dvh flex-col bg-background text-foreground">
    <header class="mx-auto flex w-full max-w-5xl items-center justify-between gap-3 px-4 py-4 md:px-8">
      <AppLogo />
      <AppButton
        variant="ghost"
        :href="primary.href"
        class="h-11 md:h-control-md"
      >
        {{ primary.label }}
      </AppButton>
    </header>

    <main class="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-4 py-12 md:px-8 md:py-20">
      <div class="max-w-2xl">
        <p
          class="mb-4 inline-flex items-center gap-2 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground"
        >
          <AppIcon
            :icon="Server"
            size="xs"
          />
          {{ name }} Cloud
        </p>
        <h1 class="text-3xl leading-tight font-semibold tracking-tight text-balance md:text-5xl">
          Это сервер Hearfolio вашей команды
        </h1>
        <p class="mt-4 text-base text-pretty text-muted-foreground md:text-lg">{{ description }}</p>
        <div class="mt-8 flex flex-col gap-2 sm:flex-row sm:items-center">
          <AppButton
            size="lg"
            :href="primary.href"
            :icon="ArrowRight"
            icon-position="end"
            class="h-11 sm:h-control-lg"
          >
            {{ primary.label }}
          </AppButton>
          <AppButton
            size="lg"
            variant="secondary"
            :href="appDownloadUrl"
            external
            :icon="Download"
            class="h-11 sm:h-control-lg"
          >
            Скачать приложение
          </AppButton>
        </div>
      </div>

      <ol class="mt-14 grid gap-3 md:mt-20 md:grid-cols-3">
        <li
          v-for="(step, index) in steps"
          :key="step.title"
          class="rounded-xl border border-border bg-card p-5"
        >
          <div class="flex items-center gap-3">
            <span
              class="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground"
              aria-hidden="true"
              >{{ index + 1 }}</span
            >
            <AppIcon
              :icon="step.icon"
              size="sm"
              tone="muted"
            />
          </div>
          <h2 class="mt-4 text-sm font-medium">{{ step.title }}</h2>
          <p class="mt-1 text-sm text-muted-foreground">{{ step.text }}</p>
        </li>
      </ol>
    </main>

    <footer class="mx-auto w-full max-w-5xl px-4 py-6 text-sm text-muted-foreground md:px-8">
      Нет учётной записи? Попросите у администратора команды ссылку-приглашение.
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ArrowRight, Download, FolderOpen, Server } from '@lucide/vue'
import AppLogo from '~/shared/components/layout/header/AppLogo.vue'

const { name, appDownloadUrl } = useAppConfig()
const router = useRouter()
const description =
  'Здесь собираются записи встреч, звонков и голосовых заметок из приложения Hearfolio: расшифровки, саммари, теги и проекты — в одном месте для всей команды.'

const steps = [
  {
    icon: Download,
    title: 'Установите приложение',
    text: 'Hearfolio для компьютера или Android записывает встречи и звонки.',
  },
  { icon: Server, title: 'Подключите этот сервер', text: 'В приложении: Настройки → Облако, адрес этой страницы.' },
  {
    icon: FolderOpen,
    title: 'Записи появятся здесь',
    text: 'С расшифровкой, названием и саммари — для всех участников.',
  },
]

// Rendered on the server with the visitor's cookie: a signed-in visitor gets the link into the app.
const { isSignedIn } = useSession()
const primary = computed(() =>
  isSignedIn.value
    ? { label: 'Перейти к записям', href: router.resolve({ name: 'recordings' }).href }
    : { label: 'Войти', href: router.resolve({ name: 'auth' }).href },
)

const title = `${name} — сервер вашей команды`
useSeoMeta({
  title,
  description,
  ogTitle: title,
  ogDescription: description,
  ogType: 'website',
  twitterCard: 'summary',
})
</script>
