<template>
  <div class="flex min-h-dvh flex-col bg-background text-foreground">
    <!-- Guests have no profile menu: the theme switch and «copy link» live in a quiet top bar. -->
    <header
      class="mx-auto flex w-full max-w-(--page-width) items-center justify-between gap-2 pt-3 md:pt-5"
      :class="PAGE_GUTTER_CLASS"
    >
      <NuxtLink
        to="/"
        class="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :aria-label="productName"
      >
        <AppLogo />
      </NuxtLink>
      <div class="flex items-center gap-1">
        <AppButton
          v-if="share"
          variant="ghost"
          text-variant="muted"
          class="max-md:h-11"
          :icon="copied ? Check : LinkIcon"
          :label="copied ? 'Скопировано' : 'Копировать ссылку'"
          @click="copyLink"
        />
        <AppThemeToggle />
      </div>
    </header>
    <!-- The same column and gutters as the app pages: readable on a desktop, a 16px gutter on a phone. -->
    <main
      class="mx-auto flex w-full max-w-(--page-width) flex-1 flex-col pt-8 pb-8 md:pt-12"
      :class="PAGE_GUTTER_CLASS"
    >
      <div
        v-if="isPending"
        class="flex flex-col gap-4"
        aria-label="Загрузка"
      >
        <AppSkeleton class="h-8 max-w-md" />
        <AppSkeleton class="h-4 max-w-48" />
        <AppSkeleton
          :lines="6"
          class="mt-6"
        />
      </div>

      <div
        v-else-if="!share"
        class="flex flex-1 items-center justify-center py-16"
      >
        <div class="max-w-sm">
          <AppResultState
            v-if="error"
            :icon="CircleAlert"
            tone="destructive"
            title="Не удалось открыть запись"
            description="Проверьте соединение и попробуйте ещё раз"
          >
            <template #actions>
              <AppButton
                label="Повторить"
                :icon="RotateCw"
                :loading="isLoading"
                @click="refetch()"
              />
            </template>
          </AppResultState>
          <AppResultState
            v-else
            :icon="LinkIcon"
            title="Ссылка недоступна"
            description="Её отозвали, срок действия истёк или запись удалили. Попросите автора поделиться заново"
          />
        </div>
      </div>

      <article
        v-else
        class="flex flex-col gap-8"
      >
        <header class="flex flex-col gap-2">
          <h1 :class="[PAGE_TITLE_CLASS, 'break-words']">
            {{ share.title || 'Запись без названия' }}
          </h1>
          <p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            <span>{{ recordedLabel }}</span>
            <template v-if="share.duration_ms">
              <span aria-hidden="true">·</span>
              <span>{{ formatDuration(share.duration_ms) }}</span>
            </template>
          </p>
        </header>

        <div
          v-if="share.audio"
          class="sticky top-2 z-10"
        >
          <ShareAudioPlayer
            ref="player"
            v-model:current-ms="currentMs"
            :src="share.audio.url"
            :expires-at="share.audio.expires_at"
            :duration-ms="share.duration_ms"
            :refresh="refetch"
          />
        </div>

        <section
          v-for="result in results"
          :key="result.id"
          class="flex flex-col gap-3"
          :aria-label="result.title"
        >
          <h2 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">{{ result.title }}</h2>
          <AppMarkdown
            :source="stripLeadingTitle(result.content, result.title)"
            size="md"
          />
        </section>

        <section
          v-if="hasTranscript"
          class="flex flex-col gap-3"
          aria-label="Расшифровка"
        >
          <h2 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Расшифровка</h2>
          <ShareTranscript
            :segments="share.transcript_segments ?? []"
            :text="share.transcript_text ?? ''"
            :current-ms="currentMs"
            :seekable="Boolean(share.audio)"
            @seek="(ms) => player?.seek(ms)"
          />
        </section>

        <p
          v-if="!share.audio && !hasTranscript && !results.length"
          class="text-sm text-muted-foreground"
        >
          Автор поделился только названием записи.
        </p>
      </article>
    </main>
    <footer class="px-4 pt-4 pb-8 text-center text-xs text-muted-foreground">
      <NuxtLink
        to="/"
        class="rounded-sm outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >Сделано в {{ productName }}</NuxtLink
      >
    </footer>
  </div>
</template>

<script setup lang="ts">
import { useClipboard } from '@vueuse/core'
import { Check, CircleAlert, Link as LinkIcon, RotateCw } from '@lucide/vue'
import AppLogo from '~/shared/components/layout/header/AppLogo.vue'
import { PAGE_GUTTER_CLASS, PAGE_TITLE_CLASS } from '~/shared/ui/app/pageContainer'
import { stripLeadingTitle } from '~/features/recording/utils/resultContent'
import ShareAudioPlayer from '../components/ShareAudioPlayer.vue'
import ShareTranscript from '../components/ShareTranscript.vue'
import { shareResults, usePublicShare } from '../composables/usePublicShare'

const props = defineProps<{ token: string }>()

const { name: productName } = useAppConfig()
const { formatDate } = useDate()
const { data: share, error, isPending, isLoading, refetch, refresh } = usePublicShare(() => props.token)
// Head tags are resolved once on the server: wait for the share before they are set.
if (import.meta.server) await refresh().catch(() => null)

const { copy, copied } = useClipboard({ legacy: true, copiedDuring: 2000 })
const copyLink = () => copy(window.location.href)

const player = ref<InstanceType<typeof ShareAudioPlayer>>()
const currentMs = ref(0)

const results = computed(() => shareResults(share.value))
const hasTranscript = computed(() =>
  Boolean(share.value && (share.value.transcript_segments?.length || share.value.transcript_text?.trim())),
)
const recordedLabel = computed(() =>
  share.value ? formatDate(share.value.recorded_at, { format: 'D MMMM YYYY, HH:mm' }) : '',
)

const seoFor = (value: typeof share.value) => {
  if (!value) {
    const title = value === null ? 'Ссылка недоступна' : productName
    return { title, description: `Запись, которой поделились через ${productName}` }
  }
  const parts = [recordedLabel.value, value.duration_ms ? formatDuration(value.duration_ms) : null]
  return { title: value.title || 'Запись без названия', description: parts.filter(Boolean).join(' · ') }
}
// The server resolves head tags after rendering, when the query entry may already be released: keep a plain copy.
const seo = ref(seoFor(share.value))
watch(share, (value) => {
  seo.value = seoFor(value)
})
useSeoMeta({
  title: () => seo.value.title,
  description: () => seo.value.description,
  ogTitle: () => seo.value.title,
  ogDescription: () => seo.value.description,
  ogType: 'article',
  ogSiteName: productName,
  // Shared recordings are private by nature: keep them out of search engines.
  robots: 'noindex, nofollow',
})
</script>
