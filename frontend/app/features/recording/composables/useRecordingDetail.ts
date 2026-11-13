import { useMutation, useQuery, useQueryCache } from '@pinia/colada'
import type { MaybeRefOrGetter } from 'vue'
import {
  aiSettingsOptions,
  recordingAiCreateResults,
  recordingAiResults,
  recordingResultsDestroy,
  recordingResultsRegenerate,
  recordingsAudio,
  recordingsEvents,
  recordingsRevokeShare,
  recordingsShare,
  recordingsUpdateShare,
  type RecordingEventReadSchema,
  type RecordingResultReadSchema,
  type RecordingResultsCreateSchema,
  type ShareLinkReadSchema,
  type ShareLinkUpsertSchema,
} from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'
import { apiErrorReason } from '~/features/organization/composables/organizationErrors'
import { recordingErrorMessage, recordingKeys } from './useRecordingMutations'

export type RecordingEvent = RecordingEventReadSchema
export type RecordingResult = RecordingResultReadSchema
export type ShareLink = ShareLinkReadSchema

/** Allowed models and defaults for members (`GET /ai-settings/options`); the AI settings screen invalidates it. */
export const useAiOptions = () => {
  const client = useApiClient()
  return useQuery({
    key: ['ai-options'],
    query: async ({ signal }) => (await aiSettingsOptions({ client, throwOnError: true, signal })).data,
    staleTime: 5 * 60_000,
  })
}

export const useRecordingEvents = (id: MaybeRefOrGetter<string>, enabled: MaybeRefOrGetter<boolean> = true) => {
  const client = useApiClient()
  return useQuery({
    key: () => [...recordingKeys.events(toValue(id))],
    query: async ({ signal }) =>
      (await recordingsEvents({ client, throwOnError: true, signal, path: { item_id: toValue(id) } })).data,
    enabled: () => toValue(enabled),
  })
}

/** Summaries of one recording; realtime `result.updated` invalidates them, so running ones finish on screen. */
export const useRecordingResults = (id: MaybeRefOrGetter<string>) => {
  const client = useApiClient()
  const queryCache = useQueryCache()
  const toast = useToast()
  const key = () => [...recordingKeys.results(toValue(id))]
  const query = useQuery({
    key,
    query: async ({ signal }) =>
      (await recordingAiResults({ client, throwOnError: true, signal, path: { item_id: toValue(id) } })).data,
  })
  const refresh = () =>
    Promise.all([
      queryCache.invalidateQueries({ key: key() }),
      queryCache.invalidateQueries({ key: [...recordingKeys.events(toValue(id))] }),
    ])

  const create = useMutation({
    mutation: async (body: RecordingResultsCreateSchema) =>
      (await recordingAiCreateResults({ client, throwOnError: true, path: { item_id: toValue(id) }, body })).data,
    onSettled: () => refresh(),
  })
  const regenerate = async (result: RecordingResult) => {
    try {
      await recordingResultsRegenerate({ client, throwOnError: true, path: { item_id: result.id } })
      toast.default('Саммари создаётся заново')
    } catch (error) {
      toast.error(recordingErrorMessage(error, 'Не удалось перезапустить саммари'))
    } finally {
      void refresh()
    }
  }
  const remove = async (result: RecordingResult) => {
    const previous = queryCache.getQueryData(key()) as RecordingResult[] | undefined
    queryCache.setQueryData(
      key(),
      previous?.filter((item) => item.id !== result.id),
    )
    try {
      await recordingResultsDestroy({ client, throwOnError: true, path: { item_id: result.id } })
      toast.default('Саммари удалено')
    } catch (error) {
      queryCache.setQueryData(key(), previous)
      toast.error(recordingErrorMessage(error, 'Не удалось удалить саммари'))
    } finally {
      void refresh()
    }
  }
  return { ...query, results: computed<RecordingResult[]>(() => query.data.value ?? []), create, regenerate, remove }
}

/** The recording's active public link (or null) and its settings. */
export const useRecordingShare = (id: MaybeRefOrGetter<string>, enabled: MaybeRefOrGetter<boolean>) => {
  const client = useApiClient()
  const queryCache = useQueryCache()
  const toast = useToast()
  const key = () => [...recordingKeys.share(toValue(id))]
  const query = useQuery({
    key,
    query: async ({ signal }) =>
      (await recordingsShare({ client, throwOnError: true, signal, path: { item_id: toValue(id) } })).data ?? null,
    enabled: () => toValue(enabled),
  })
  const afterWrite = () => queryCache.invalidateQueries({ key: [...recordingKeys.events(toValue(id))] })

  const save = async (body: ShareLinkUpsertSchema) => {
    try {
      const { data } = await recordingsUpdateShare({
        client,
        throwOnError: true,
        path: { item_id: toValue(id) },
        body,
      })
      queryCache.setQueryData(key(), data)
      void afterWrite()
      return data
    } catch (error) {
      if (apiErrorReason(error) === 'unknown_result_ids') {
        // A summary was deleted meanwhile: refresh the list so the next save leaves it out.
        void queryCache.invalidateQueries({ key: [...recordingKeys.results(toValue(id))] })
        toast.error('Одно из саммари уже удалено', { description: 'Список обновлён — выберите саммари ещё раз' })
      } else toast.error(recordingErrorMessage(error, 'Не удалось сохранить ссылку'))
      throw error
    }
  }
  const revoke = async () => {
    try {
      await recordingsRevokeShare({ client, throwOnError: true, path: { item_id: toValue(id) } })
      queryCache.setQueryData(key(), null)
      void afterWrite()
    } catch (error) {
      toast.error(recordingErrorMessage(error, 'Не удалось отключить ссылку'))
      throw error
    }
  }
  return { ...query, link: computed<ShareLink | null>(() => query.data.value ?? null), save, revoke }
}

/** Presigned audio URL; cached outside the recording's key so realtime refetches never interrupt playback. */
export const useRecordingAudio = (id: MaybeRefOrGetter<string>, enabled: MaybeRefOrGetter<boolean>) => {
  const client = useApiClient()
  return useQuery({
    key: () => [...recordingKeys.audio(toValue(id))],
    query: async ({ signal }) =>
      (await recordingsAudio({ client, throwOnError: true, signal, path: { item_id: toValue(id) } })).data,
    enabled: () => toValue(enabled),
    staleTime: 5 * 60_000,
  })
}
