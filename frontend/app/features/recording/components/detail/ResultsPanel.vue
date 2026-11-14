<template>
  <!-- No boxes here: a summary is a titled piece of text across the content column, apart from the next one by space. -->
  <div class="flex flex-col gap-8">
    <AppButton
      v-if="results.length"
      variant="ghost"
      text-variant="muted"
      :icon="Sparkles"
      label="Создать саммари"
      class="-ml-3 self-start max-md:h-11"
      :disabled="!transcribed"
      :title="transcribed ? undefined : 'Саммари можно создать после расшифровки'"
      @click="createOpen = true"
    />

    <AppAlert
      v-if="error && !results.length"
      tone="destructive"
      title="Не удалось загрузить саммари"
    >
      <AppTextButton
        label="Повторить"
        weight="medium"
        @click="refetch()"
      />
    </AppAlert>
    <div
      v-else-if="isLoading && !results.length"
      class="flex flex-col gap-8"
      aria-busy="true"
      aria-label="Загрузка саммари"
    >
      <div
        v-for="row in 2"
        :key="row"
        class="flex flex-col gap-3"
      >
        <AppSkeleton class="h-5 w-40" />
        <AppSkeleton :lines="4" />
      </div>
    </div>
    <div
      v-else-if="!results.length"
      class="flex flex-col items-start gap-4 py-2"
    >
      <span
        class="flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground"
        aria-hidden="true"
      >
        <AppIcon
          :icon="Sparkles"
          size="md"
        />
      </span>
      <div class="flex flex-col gap-1">
        <h3 class="text-lg font-semibold">Саммари пока нет</h3>
        <p class="max-w-md text-sm text-muted-foreground">
          {{
            transcribed
              ? 'Выберите шаблоны — например «Кратко» или «Задачи и ответственные» — или напишите свой запрос, и модель соберёт главное из записи'
              : 'Когда расшифровка будет готова, здесь можно будет собрать главное из записи'
          }}
        </p>
      </div>
      <AppButton
        :icon="Sparkles"
        label="Создать саммари"
        class="max-md:h-11"
        :disabled="!transcribed"
        @click="createOpen = true"
      />
    </div>

    <article
      v-for="result in results"
      :key="result.id"
      class="flex flex-col gap-4"
      :aria-label="result.title"
    >
      <header class="flex items-start gap-1">
        <div class="flex min-w-0 flex-1 flex-col gap-0.5">
          <h3 class="text-lg leading-snug font-semibold break-words">{{ result.title }}</h3>
          <p class="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
            <span
              v-if="result.status !== 'done'"
              :class="result.status === 'failed' ? 'text-destructive' : undefined"
              >{{ RESULT_STATUS_LABELS[result.status].label }}</span
            >
            <span v-else>{{ formatDate(result.updated_at, { format: 'D MMMM, HH:mm' }) }}</span>
            <span aria-hidden="true">·</span>
            <span class="break-all">{{ shortModel(result.model) }}</span>
          </p>
        </div>
        <AppButton
          v-if="result.status === 'done'"
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="size-11 shrink-0 md:size-control-md"
          :icon="copiedId === result.id ? Check : Copy"
          :aria-label="`Копировать текст: ${result.title}`"
          :title="copiedId === result.id ? 'Скопировано' : 'Копировать текст'"
          @click="copyResult(result)"
        />
        <AppMenu
          :actions="actionsFor(result)"
          align="end"
        >
          <template #trigger>
            <AppButton
              variant="ghost"
              size="icon"
              text-variant="muted"
              class="size-11 shrink-0 md:size-control-md"
              :icon="Ellipsis"
              :aria-label="`Действия: ${result.title}`"
            />
          </template>
        </AppMenu>
      </header>
      <AppMarkdown
        v-if="result.status === 'done'"
        size="md"
        :source="stripLeadingTitle(result.content, result.title)"
      />
      <div
        v-else-if="result.status === 'failed'"
        class="flex flex-col items-start gap-3"
      >
        <p class="text-sm text-muted-foreground">
          {{ processingErrorText(result.error_code, result.error_message) || 'Модель не смогла собрать саммари' }}
        </p>
        <AppButton
          size="sm"
          variant="secondary"
          :icon="RotateCcw"
          label="Повторить"
          class="max-md:h-11"
          @click="regenerate(result)"
        />
      </div>
      <div
        v-else
        class="flex flex-col gap-3"
        role="status"
      >
        <p class="text-sm text-muted-foreground">
          {{ result.status === 'running' ? 'Модель пишет саммари…' : 'Ждёт своей очереди…' }}
        </p>
        <AppSkeleton :lines="3" />
      </div>
    </article>

    <CreateResultModal
      v-model="createOpen"
      :create="create"
    />
    <AppConfirmModal
      v-model="confirmOpen"
      title="Удалить саммари?"
      :subtitle="pendingDelete ? `«${pendingDelete.title}» исчезнет у всех участников` : ''"
      confirm-text="Удалить"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="confirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { Check, Copy, Ellipsis, RotateCcw, Sparkles, Trash2 } from '@lucide/vue'
import { useClipboard } from '@vueuse/core'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import type { RecordingDetail } from '../../resources/recording'
import type { RecordingResult, useRecordingResults } from '../../composables/useRecordingDetail'
import { processingErrorText, RESULT_STATUS_LABELS } from '../../composables/useRecordingLabels'
import { stripLeadingTitle } from '../../utils/resultContent'
import CreateResultModal from './CreateResultModal.vue'

const props = defineProps<{
  recording: RecordingDetail
  state: ReturnType<typeof useRecordingResults>
  userId: string | null
  isAdmin: boolean
}>()

const { results, isLoading, error, refetch, regenerate, remove, create } = props.state
const transcribed = computed(() => props.recording.status === 'transcribed')
const createOpen = ref(false)
const confirmOpen = ref(false)
const pendingDelete = ref<RecordingResult | null>(null)
const { copy } = useClipboard({ legacy: true })
const toast = useToast()
const { formatDate } = useDate()

const shortModel = (model: string) => model.split('/').pop() ?? model

// Own results; automatic ones also by the recording's author; anything for org admins (docs/product.md).
const canDelete = (result: RecordingResult) =>
  props.isAdmin ||
  (Boolean(props.userId) &&
    (result.created_by_id === props.userId ||
      (!result.created_by_id && props.recording.created_by_id === props.userId)))

const copiedId = ref<string | null>(null)
let copiedTimer: ReturnType<typeof setTimeout> | undefined
const copyResult = async (result: RecordingResult) => {
  await copy(result.content)
  copiedId.value = result.id
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => (copiedId.value = null), 2000)
  toast.default('Саммари скопировано')
}
onBeforeUnmount(() => clearTimeout(copiedTimer))

const actionsFor = (result: RecordingResult): AppMenuAction[] => [
  {
    label: 'Создать заново',
    icon: RotateCcw,
    disabled: !transcribed.value,
    action: () => regenerate(result),
  },
  {
    label: 'Удалить',
    icon: Trash2,
    destructive: true,
    separatorBefore: true,
    hidden: !canDelete(result),
    action: () => {
      pendingDelete.value = result
      confirmOpen.value = true
    },
  },
]

const confirmDelete = async () => {
  if (pendingDelete.value) await remove(pendingDelete.value)
}
</script>
