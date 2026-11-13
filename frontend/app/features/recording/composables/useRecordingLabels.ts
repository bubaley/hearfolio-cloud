import {
  CircleAlert,
  CircleCheck,
  CirclePlus,
  CloudUpload,
  FileAudio,
  FolderInput,
  Link2,
  Link2Off,
  Pencil,
  RotateCcw,
  Sparkles,
  Tags,
  Trash2,
} from '@lucide/vue'
import type { Component } from 'vue'
import type { RecordingEventKind, RecordingStatus, ResultStatus } from '~/shared/api/generated'
import type { AppLabelConfig } from '~/shared/ui/app/types/label-types'
import type { Recording } from '../resources/recording'

/** What the list row and the page header show for a recording that is not simply «ready». */
export type RecordingStatusView = AppLabelConfig & {
  /** Still moving: show a spinner and refresh on realtime events. */
  active: boolean
  /** 0–100 while transcribing. */
  progress: number | null
}

export const STATUS_FILTER_OPTIONS: { label: string; value: RecordingStatus }[] = [
  { label: 'Готово', value: 'transcribed' },
  { label: 'Расшифровка', value: 'transcribing' },
  { label: 'В очереди', value: 'queued' },
  { label: 'Загружается', value: 'awaiting_upload' },
  { label: 'Ошибка', value: 'failed' },
]

export const isProcessing = (status: RecordingStatus) =>
  status === 'awaiting_upload' || status === 'queued' || status === 'transcribing'

/** Null for a finished recording: the list shows nothing for the normal state. */
export const getRecordingStatusView = (
  recording: Pick<Recording, 'status' | 'upload_state' | 'segments_done' | 'segments_total' | 'progress'>,
): RecordingStatusView | null => {
  switch (recording.status) {
    case 'awaiting_upload':
      return recording.upload_state === 'failed'
        ? { label: 'Ошибка загрузки', icon: CircleAlert, tone: 'destructive', active: false, progress: null }
        : { label: 'Загружается', icon: CloudUpload, tone: 'muted', active: true, progress: null }
    case 'queued':
      return { label: 'В очереди', icon: CloudUpload, tone: 'muted', active: true, progress: null }
    case 'transcribing': {
      const total = recording.segments_total
      return {
        label: total ? `Расшифровка ${recording.segments_done}/${total}` : 'Расшифровка',
        icon: Sparkles,
        tone: 'info',
        active: true,
        progress: recording.progress,
      }
    }
    case 'failed':
      return { label: 'Ошибка', icon: CircleAlert, tone: 'destructive', active: false, progress: null }
    default:
      return null
  }
}

export const RESULT_STATUS_LABELS: Record<ResultStatus, AppLabelConfig> = {
  queued: { label: 'В очереди', icon: CloudUpload, tone: 'muted' },
  running: { label: 'Готовится', icon: Sparkles, tone: 'info' },
  done: { label: 'Готово', icon: CircleCheck, tone: 'success' },
  failed: { label: 'Ошибка', icon: CircleAlert, tone: 'destructive' },
}

const EVENT_LABELS: Record<RecordingEventKind, { label: string; icon: Component }> = {
  created: { label: 'Создал(а) запись', icon: CirclePlus },
  uploaded: { label: 'Аудио загружено', icon: CloudUpload },
  transcribed: { label: 'Расшифровка готова', icon: FileAudio },
  failed: { label: 'Ошибка обработки', icon: CircleAlert },
  renamed: { label: 'Переименовал(а)', icon: Pencil },
  moved: { label: 'Изменил(а) проект', icon: FolderInput },
  tagged: { label: 'Изменил(а) теги', icon: Tags },
  shared: { label: 'Открыл(а) доступ по ссылке', icon: Link2 },
  unshared: { label: 'Закрыл(а) доступ по ссылке', icon: Link2Off },
  result_created: { label: 'Создано саммари', icon: Sparkles },
  restored: { label: 'Восстановил(а) запись', icon: RotateCcw },
  deleted: { label: 'Удалил(а) запись', icon: Trash2 },
}

export const getEventLabel = (kind: RecordingEventKind) => EVENT_LABELS[kind] ?? { label: kind, icon: CirclePlus }

// Stable `error_code` values of recordings and summaries (docs/product.md → API contract); unknown codes fall back to
// the server's Russian `error_message`.
const PROCESSING_ERRORS: Record<string, string> = {
  not_configured: 'AI не настроен: администратору нужно добавить ключ OpenRouter и модели в «AI и модели»',
  auth: 'Ключ OpenRouter не подошёл — проверьте его в «AI и модели»',
  payment: 'На счёте OpenRouter закончились средства',
  forbidden: 'Провайдер отказал в доступе к модели',
  rate_limited: 'Провайдер временно ограничил запросы — повторите через минуту',
  bad_request: 'Провайдер не принял запрос',
  model_unavailable: 'Модель сейчас недоступна — выберите другую или повторите позже',
  too_large: 'Фрагмент слишком большой для модели',
  server: 'У провайдера сбой — повторите позже',
  network: 'Нет связи с провайдером',
  timeout: 'Провайдер не ответил вовремя',
  invalid_response: 'Модель вернула непонятный ответ',
  incomplete: 'Модель вернула неполный ответ',
  empty: 'Модель вернула пустой ответ',
  content_filter: 'Провайдер отклонил содержимое',
  storage: 'Не удалось прочитать аудио из хранилища',
  audio: 'Не удалось прочитать аудиофайл — возможно, он повреждён',
  upload_size_mismatch: 'Файл загрузился не полностью — загрузите его заново',
  internal: 'Внутренняя ошибка сервера',
}

export const processingErrorText = (code: string | null | undefined, message: string | null | undefined) =>
  (code && PROCESSING_ERRORS[code]) || message || ''

export const recordingTitle = (recording: Pick<Recording, 'title' | 'status'>) =>
  recording.title.trim() || (isProcessing(recording.status) ? 'Новая запись' : 'Без названия')
