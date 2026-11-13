<template>
  <div class="flex h-full min-h-0 flex-col">
    <div class="flex h-12 shrink-0 items-center gap-1 px-2 md:px-4">
      <nav
        aria-label="Путь"
        class="flex min-w-0 flex-1 items-center gap-1 text-sm"
      >
        <AppButton
          variant="ghost"
          size="sm"
          text-variant="muted"
          :icon="ArrowLeft"
          :label="backLabel"
          class="max-w-48 shrink-0 max-md:h-11 [&>span]:truncate"
          @click="goBack"
        />
        <template v-if="recording">
          <span class="hidden min-w-0 items-center gap-1 md:flex">
            <AppIcon
              :icon="ChevronRight"
              size="xs"
              class="shrink-0 text-muted-foreground"
            />
            <span class="min-w-0 truncate text-muted-foreground">{{ title }}</span>
          </span>
        </template>
      </nav>
      <template v-if="recording">
        <SharePopover
          :recording-id="recording.id"
          :results="resultsState.results.value"
        />
        <AppMenu
          :actions="menuActions"
          align="end"
        >
          <template #trigger>
            <AppButton
              variant="ghost"
              size="icon"
              text-variant="muted"
              class="size-11 md:size-control-md"
              :icon="Ellipsis"
              aria-label="Действия с записью"
            />
          </template>
        </AppMenu>
      </template>
    </div>

    <div
      ref="scroller"
      class="min-h-0 flex-1 overflow-y-auto"
      tabindex="-1"
    >
      <div
        v-if="error && !recording"
        class="flex min-h-full items-center justify-center px-4 py-10"
      >
        <div class="w-full max-w-sm">
          <AppResultState
            v-if="isApiError(error, 404)"
            :icon="SearchX"
            title="Запись не найдена"
            description="Её удалили, сделали личной или перенесли в проект, к которому у вас нет доступа"
          >
            <template #actions>
              <AppButton
                variant="outline"
                label="Ко всем записям"
                :to="{ name: 'recordings' }"
              />
            </template>
          </AppResultState>
          <AppResultState
            v-else
            :icon="CircleAlert"
            tone="destructive"
            title="Не удалось открыть запись"
            description="Проверьте подключение и попробуйте ещё раз"
          >
            <template #actions>
              <AppButton
                variant="outline"
                label="Повторить"
                :icon="RotateCcw"
                @click="refetch()"
              />
            </template>
          </AppResultState>
        </div>
      </div>

      <div
        v-else-if="!recording"
        class="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 pt-6 md:px-6 md:pt-10"
        aria-busy="true"
        aria-label="Загрузка записи"
      >
        <AppSkeleton class="h-9 w-3/4" />
        <div class="flex flex-col gap-3">
          <div
            v-for="row in 4"
            :key="row"
            class="flex gap-6"
          >
            <AppSkeleton class="h-4 w-24" />
            <AppSkeleton class="h-4 w-40" />
          </div>
        </div>
        <AppSkeleton :lines="6" />
      </div>

      <article
        v-else
        class="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 pt-5 pb-16 md:px-6 md:pt-10"
      >
        <RecordingTitle
          :title="recording.title"
          :placeholder="title"
          @save="(value) => save({ title: value })"
        />
        <RecordingProperties
          :recording="recording"
          :is-author="isAuthor"
          @project="moveTo"
          @tags="setTags"
          @visibility="(value) => save({ visibility: value })"
        />
        <RecordingNotices
          :recording="recording"
          :retry="() => mutations.retry(recording!.id)"
          @suggestion="(accept) => mutations.answerSuggestion(recording!.id, accept)"
        />

        <AppTabs
          v-model="tab"
          query-key="tab"
          :tabs="tabs"
          aria-label="Разделы записи"
          content-class="pt-5"
          select-class="max-md:h-11 max-md:[&>button]:h-9 max-md:[&>button]:px-3"
        >
          <AppTabPanel tab-value="transcript">
            <TranscriptView
              v-if="recording.transcript_segments.length || recording.transcript_text"
              :segments="recording.transcript_segments"
              :text="recording.transcript_text"
              :player="player"
              :scroller="scroller ?? null"
            />
            <AppResultState
              v-else
              :icon="processing ? Sparkles : FileAudio"
              :title="processing ? 'Текст появится здесь' : 'Расшифровки нет'"
              :description="
                processing
                  ? 'Расшифровка идёт по частям — первые фразы покажутся, как только будет готова первая часть'
                  : recording.status === 'failed'
                    ? 'Расшифровка не удалась — нажмите «Повторить» выше'
                    : 'Запустите расшифровку из меню «…» → «Расшифровать заново»'
              "
              class="py-8"
            />
          </AppTabPanel>
          <AppTabPanel tab-value="summary">
            <ResultsPanel
              :recording="recording"
              :state="resultsState"
              :user-id="userId"
              :is-admin="isAdmin"
            />
          </AppTabPanel>
          <AppTabPanel tab-value="history">
            <EventsList :state="eventsState" />
          </AppTabPanel>
        </AppTabs>
      </article>
    </div>

    <AudioPlayer
      v-if="recording && recording.upload_state === 'uploaded'"
      :player="player"
      class="shrink-0"
    />

    <RetranscribeModal
      v-model="retranscribeOpen"
      :submit="(model) => mutations.retranscribe(recordingId, model)"
    />
    <AppConfirmModal
      v-model="deleteOpen"
      title="Удалить запись?"
      :subtitle="`«${title}» пропадёт у всех участников. Восстановить её можно в течение 30 дней`"
      confirm-text="Удалить"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="confirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { useClipboard } from '@vueuse/core'
import {
  ArrowLeft,
  AudioLines,
  ChevronRight,
  CircleAlert,
  Copy,
  Download,
  Ellipsis,
  FileAudio,
  FileText,
  Lock,
  RotateCcw,
  SearchX,
  Sparkles,
  Trash2,
  Users,
} from '@lucide/vue'
import { recordingsAudio } from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { useApiClient, useResourceItem } from '~/shared/api/useResource'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import { recordingResource, type RecordingDetail, type RecordingPatch, type TagBrief } from '../resources/recording'
import type { ProjectBrief } from '~/features/project/resources/project'
import { useAudioPlayer } from '../composables/useAudioPlayer'
import { useRecordingAudio, useRecordingEvents, useRecordingResults } from '../composables/useRecordingDetail'
import { isProcessing, recordingTitle } from '../composables/useRecordingLabels'
import { recordingErrorMessage, useRecordingMutations } from '../composables/useRecordingMutations'
import { downloadText, recordingToMarkdown, recordingToText, safeFilename } from '../utils/recordingExport'
import AudioPlayer from '../components/detail/AudioPlayer.vue'
import EventsList from '../components/detail/EventsList.vue'
import RecordingNotices from '../components/detail/RecordingNotices.vue'
import RecordingProperties from '../components/detail/RecordingProperties.vue'
import RecordingTitle from '../components/detail/RecordingTitle.vue'
import ResultsPanel from '../components/detail/ResultsPanel.vue'
import RetranscribeModal from '../components/detail/RetranscribeModal.vue'
import SharePopover from '../components/detail/SharePopover.vue'
import TranscriptView from '../components/detail/TranscriptView.vue'

const route = useRoute()
const router = useRouter()
const client = useApiClient()
const toast = useToast()
const { user } = useSession()
const { isAdmin } = useOrganizationRole()
const { formatDate } = useDate()
const mutations = useRecordingMutations()

const recordingId = computed(() => String(route.params.id))
const { data, error, refetch } = useResourceItem(recordingResource, recordingId)
// Retrieve returns the detail schema (with the transcript); the descriptor is typed by the list rows.
const recording = computed(() => data.value as RecordingDetail | undefined)

const userId = computed(() => user.value?.id ?? null)
const isAuthor = computed(() => Boolean(recording.value && recording.value.created_by_id === userId.value))
const canDelete = computed(() => isAuthor.value || isAdmin.value)
const title = computed(() => (recording.value ? recordingTitle(recording.value) : 'Запись'))
const processing = computed(() => Boolean(recording.value && isProcessing(recording.value.status)))

useHead({ title: () => title.value })

const resultsState = useRecordingResults(recordingId)
const tab = ref('transcript')
const eventsState = useRecordingEvents(recordingId, () => tab.value === 'history')
const tabs = computed(() => {
  const count = resultsState.results.value.length
  return [
    { label: 'Расшифровка', value: 'transcript' },
    { label: count ? `Саммари · ${count}` : 'Саммари', value: 'summary' },
    { label: 'История', value: 'history' },
  ]
})

const audio = useRecordingAudio(recordingId, () => recording.value?.upload_state === 'uploaded')
const player = useAudioPlayer({
  url: () => audio.data.value,
  refresh: async () => (await audio.refetch()).data,
  title: () => title.value,
  durationMs: () => recording.value?.duration_ms ?? 0,
})
const scroller = ref<HTMLElement>()

// Back returns to the list the user came from (with its filters); a direct link goes to «Все записи».
const previous = String((import.meta.client && router.options.history.state.back) || '')
const fromProject = /^\/projects\/[^/?]+(\?|$)/.test(previous)
const cameFromList = fromProject || /^\/recordings(\?|$)/.test(previous)
const backLabel = fromProject ? 'Проект' : cameFromList && previous.includes('personal=1') ? 'Личные' : 'Все записи'
const goBack = () => {
  if (cameFromList) router.back()
  else void navigateTo({ name: 'recordings' })
}

const save = (body: RecordingPatch, optimistic: Partial<RecordingDetail> = {}) =>
  mutations.patch(recordingId.value, body, optimistic).catch(() => undefined)

const moveTo = (project: ProjectBrief | null) => save({ project_id: project?.id ?? null }, { project })
const setTags = (tags: TagBrief[]) => save({ tag_ids: tags.map((tag) => tag.id) }, { tags })

const { copy } = useClipboard({ legacy: true })
const hasText = computed(() => Boolean(recording.value?.transcript_text.trim()))

const exportText = (kind: 'txt' | 'md') => {
  const current = recording.value
  if (!current) return
  const name = safeFilename(title.value)
  if (kind === 'txt') downloadText(`${name}.txt`, recordingToText(current, title.value), 'text/plain')
  else
    downloadText(
      `${name}.md`,
      recordingToMarkdown(
        current,
        title.value,
        formatDate(current.recorded_at, { format: 'D MMMM YYYY, HH:mm' }) ?? '',
        resultsState.results.value,
      ),
      'text/markdown',
    )
}

const downloadAudio = async () => {
  try {
    const { data: link } = await recordingsAudio({
      client,
      throwOnError: true,
      path: { item_id: recordingId.value },
      query: { download: true },
    })
    window.location.assign(link.url)
  } catch (failure) {
    toast.error(recordingErrorMessage(failure, 'Не удалось скачать аудио'))
  }
}

const retranscribeOpen = ref(false)
const deleteOpen = ref(false)

const menuActions = computed<AppMenuAction[]>(() => {
  const current = recording.value
  const uploaded = current?.upload_state === 'uploaded'
  return [
    {
      label: 'Копировать текст',
      icon: Copy,
      disabled: !hasText.value,
      action: async () => {
        await copy(current?.transcript_text ?? '')
        toast.default('Текст скопирован')
      },
    },
    { label: 'Скачать аудио', icon: Download, disabled: !uploaded, action: downloadAudio },
    { label: 'Скачать .txt', icon: FileText, disabled: !hasText.value, action: () => exportText('txt') },
    { label: 'Скачать .md', icon: FileText, disabled: !hasText.value, action: () => exportText('md') },
    {
      label: 'Расшифровать заново',
      icon: AudioLines,
      separatorBefore: true,
      disabled: !uploaded || current?.status === 'transcribing',
      action: () => {
        retranscribeOpen.value = true
      },
    },
    {
      label: current?.visibility === 'personal' ? 'Сделать общей' : 'Сделать личной',
      icon: current?.visibility === 'personal' ? Users : Lock,
      hidden: !isAuthor.value,
      action: () => void save({ visibility: current?.visibility === 'personal' ? 'organization' : 'personal' }),
    },
    {
      label: 'Удалить',
      icon: Trash2,
      destructive: true,
      separatorBefore: true,
      hidden: !canDelete.value,
      action: () => {
        deleteOpen.value = true
      },
    },
  ]
})

const confirmDelete = async () => {
  const current = recording.value
  if (!current) return
  await mutations.remove(current.id, title.value)
  await navigateTo({ name: 'recordings' })
}
</script>
