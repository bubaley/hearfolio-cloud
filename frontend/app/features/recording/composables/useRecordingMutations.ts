import { useQueryCache } from '@pinia/colada'
import {
  recordingAiRetranscribe,
  recordingAiRetry,
  recordingsAcceptProjectSuggestion,
  recordingsDestroy,
  recordingsDismissProjectSuggestion,
  recordingsPartialUpdate,
  recordingsRestore,
} from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { resourceKeys } from '~/shared/api/resource'
import { useApiClient } from '~/shared/api/useResource'
import { recordingResource, type RecordingDetail, type RecordingPatch } from '../resources/recording'

export const recordingKeys = {
  ...resourceKeys(recordingResource),
  events: (id: string) => ['recordings', id, 'events'] as const,
  results: (id: string) => ['recordings', id, 'results'] as const,
  share: (id: string) => ['recordings', id, 'share'] as const,
  // Outside the recording's prefix: a realtime refetch of the recording must not swap the playing audio URL.
  audio: (id: string) => ['recording-audio', id] as const,
}

/** Russian text for a failed recording request: the API envelope message when it has one. */
export const recordingErrorMessage = (error: unknown, fallback: string) => {
  if (isApiError(error, 403)) return 'Недостаточно прав для этого действия'
  if (isApiError(error, 404)) return 'Запись не найдена или к ней нет доступа'
  if (isApiError(error) && error.status >= 400 && error.status < 500 && error.message) return error.message
  return fallback
}

/**
 * Writes on one recording. Edits are optimistic: the detail cache changes at once, the server response replaces it,
 * a failure restores the previous value and shows a toast. Lists refetch by invalidation afterwards.
 */
export const useRecordingMutations = () => {
  const client = useApiClient()
  const queryCache = useQueryCache()
  const toast = useToast()

  const detail = (id: string) => queryCache.getQueryData(recordingKeys.detail(id)) as RecordingDetail | undefined
  const store = (item: RecordingDetail) => queryCache.setQueryData(recordingKeys.detail(item.id), item)
  const refreshAround = async (id: string) => {
    await Promise.all([
      queryCache.invalidateQueries({ key: recordingKeys.lists }),
      queryCache.invalidateQueries({ key: recordingKeys.events(id) }),
    ])
  }

  /** PATCH with `optimistic` fields shown right away (e.g. the chosen project object next to `project_id`). */
  const patch = async (id: string, body: RecordingPatch, optimistic: Partial<RecordingDetail> = {}) => {
    const previous = detail(id)
    if (previous) store({ ...previous, ...(body as Partial<RecordingDetail>), ...optimistic })
    try {
      const { data } = await recordingsPartialUpdate({ client, throwOnError: true, path: { item_id: id }, body })
      store(data)
      void refreshAround(id)
      return data
    } catch (error) {
      if (previous) store(previous)
      toast.error(recordingErrorMessage(error, 'Не удалось сохранить изменения'))
      throw error
    }
  }

  const run = async (id: string, request: () => Promise<{ data: RecordingDetail }>, fallback: string) => {
    try {
      const { data } = await request()
      store(data)
      void refreshAround(id)
      return data
    } catch (error) {
      toast.error(recordingErrorMessage(error, fallback))
      throw error
    }
  }

  const restore = (id: string) =>
    run(id, () => recordingsRestore({ client, throwOnError: true, path: { item_id: id } }), 'Не удалось восстановить')

  /** Soft delete with «Отменить» in the toast (restore works for 30 days; the toast is the quick path). */
  const remove = async (id: string, title: string) => {
    try {
      await recordingsDestroy({ client, throwOnError: true, path: { item_id: id } })
    } catch (error) {
      toast.error(recordingErrorMessage(error, 'Не удалось удалить запись'))
      throw error
    }
    void queryCache.invalidateQueries({ key: recordingKeys.lists })
    toast.default(`Запись «${title}» удалена`, {
      description: 'Её можно восстановить в течение 30 дней',
      duration: 8000,
      action: { label: 'Отменить', onClick: () => void restore(id).then(() => toast.default('Запись восстановлена')) },
    })
  }

  const retry = (id: string) =>
    run(
      id,
      () => recordingAiRetry({ client, throwOnError: true, path: { item_id: id } }),
      'Не удалось запустить обработку',
    )

  const retranscribe = (id: string, model: string | null) =>
    run(
      id,
      () => recordingAiRetranscribe({ client, throwOnError: true, path: { item_id: id }, body: { model } }),
      'Не удалось запустить расшифровку',
    )

  const answerSuggestion = (id: string, accept: boolean) =>
    run(
      id,
      () =>
        (accept ? recordingsAcceptProjectSuggestion : recordingsDismissProjectSuggestion)({
          client,
          throwOnError: true,
          path: { item_id: id },
        }),
      'Не удалось сохранить ответ',
    )

  return { patch, remove, restore, retry, retranscribe, answerSuggestion }
}
