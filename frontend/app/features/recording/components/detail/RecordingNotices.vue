<template>
  <div
    v-if="suggestion || processing || failed"
    class="flex flex-col gap-2"
  >
    <AppCard
      v-if="suggestion"
      variant="muted"
      padding="sm"
      class="flex flex-col gap-2 sm:flex-row sm:items-center"
    >
      <div class="flex min-w-0 flex-1 items-center gap-2.5 text-sm">
        <AppIcon
          :icon="Sparkles"
          size="sm"
          tone="primary"
          class="shrink-0"
        />
        <span class="min-w-0"
          >Похоже на проект <span class="font-medium">«{{ suggestion.name }}»</span></span
        >
      </div>
      <AppTemplateActions
        size="sm"
        :actions="[
          { label: 'Нет', variant: 'ghost', textVariant: 'muted', action: () => emit('suggestion', false) },
          { label: 'Перенести', variant: 'secondary', icon: FolderInput, action: () => emit('suggestion', true) },
        ]"
      />
    </AppCard>

    <AppCard
      v-if="processing"
      variant="muted"
      padding="sm"
      class="flex flex-col gap-2.5"
      role="status"
    >
      <div class="flex items-start gap-2.5">
        <AppIcon
          :icon="Sparkles"
          loading
          size="sm"
          class="mt-0.5 shrink-0 text-muted-foreground"
        />
        <div class="flex min-w-0 flex-1 flex-col gap-0.5">
          <span class="text-sm font-medium">{{ processing.title }}</span>
          <span class="text-xs text-muted-foreground">{{ processing.hint }}</span>
        </div>
        <span
          v-if="recording.status === 'transcribing'"
          class="shrink-0 text-xs text-muted-foreground tabular-nums"
          >{{ recording.progress }}%</span
        >
      </div>
      <AppProgress
        v-if="recording.status === 'transcribing'"
        :value="recording.progress"
        tone="info"
        class="h-1"
        aria-label="Прогресс расшифровки"
      />
    </AppCard>

    <AppAlert
      v-if="failed"
      tone="destructive"
      :title="recording.upload_state === 'failed' ? 'Аудио не загрузилось' : 'Не удалось расшифровать запись'"
    >
      <p>{{ errorText }}</p>
      <div
        v-if="recording.upload_state !== 'failed'"
        class="mt-2 flex flex-wrap gap-2"
      >
        <AppButton
          size="sm"
          variant="outline"
          :icon="RotateCcw"
          label="Повторить"
          :loading="retryState.loading.value"
          @click="retryState.execute"
        />
      </div>
    </AppAlert>
  </div>
</template>

<script setup lang="ts">
import { FolderInput, RotateCcw, Sparkles } from '@lucide/vue'
import type { RecordingDetail } from '../../resources/recording'
import { processingErrorText } from '../../composables/useRecordingLabels'

const props = defineProps<{ recording: RecordingDetail; retry: () => Promise<unknown> }>()
const emit = defineEmits<{ suggestion: [accept: boolean] }>()

const suggestion = computed(() =>
  props.recording.project_suggestion_state === 'pending' && !props.recording.project_id
    ? props.recording.suggested_project
    : null,
)

const processing = computed(() => {
  const recording = props.recording
  switch (recording.status) {
    case 'awaiting_upload':
      return recording.upload_state === 'failed'
        ? null
        : { title: 'Аудио загружается', hint: 'Расшифровка начнётся сама, как только файл дойдёт до сервера' }
    case 'queued':
      return { title: 'В очереди на расшифровку', hint: 'Обычно это занимает меньше минуты' }
    case 'transcribing':
      return {
        title: recording.segments_total
          ? `Расшифровка: ${recording.segments_done} из ${recording.segments_total} частей`
          : 'Расшифровка',
        hint: 'Текст появляется по мере готовности частей — страницу можно не обновлять',
      }
    default:
      return null
  }
})

const failed = computed(
  () =>
    props.recording.status === 'failed' ||
    (props.recording.status === 'awaiting_upload' && props.recording.upload_state === 'failed'),
)

const errorText = computed(
  () =>
    processingErrorText(props.recording.error_code, props.recording.error_message) ||
    'Попробуйте ещё раз — уже готовые части не потеряются',
)

// The mutation already shows the error toast.
const retryState = useActionState(() => props.retry().catch(() => undefined))
</script>
