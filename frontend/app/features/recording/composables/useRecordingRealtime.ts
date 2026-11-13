import { useQueryCache } from '@pinia/colada'
import { useDebounceFn } from '@vueuse/core'
import { recordingKeys } from './useRecordingMutations'

type RecordingEvent = { id?: string }
type ResultEvent = { recording_id?: string }

/**
 * Live recordings for the workspace: listens to the organization channel and marks the matching queries stale, so
 * whatever is on screen refetches through the visibility-checked API (events carry ids only). Transcription sends
 * an event per finished chunk, so list refetches are debounced; the open recording refetches at once.
 */
export const useRecordingRealtime = () => {
  const queryCache = useQueryCache()
  const setupStore = useSetupStore()

  const refreshLists = useDebounceFn(() => queryCache.invalidateQueries({ key: recordingKeys.lists }), 600, {
    maxWait: 3000,
  })

  const onMessage = (type: string, data: unknown) => {
    switch (type) {
      case 'recording.updated':
      case 'recording.deleted': {
        const id = (data as RecordingEvent | null)?.id
        if (id) void queryCache.invalidateQueries({ key: recordingKeys.detail(id) })
        void refreshLists()
        break
      }
      case 'result.updated': {
        const id = (data as ResultEvent | null)?.recording_id
        if (id) void queryCache.invalidateQueries({ key: recordingKeys.results(id) })
        break
      }
      case 'recordings.resync':
        void queryCache.invalidateQueries({ key: recordingKeys.all })
        break
    }
  }

  return useWebSocketService(
    () => {
      const id = setupStore.state.organization?.id
      return id ? `organizations/${id}` : null
    },
    { onMessage },
  )
}
