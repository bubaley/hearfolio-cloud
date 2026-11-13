import { useQuery } from '@pinia/colada'
import { tagsUsage } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'
import { pluralize } from '~/features/project/composables/projectLabels'

/**
 * Recordings per tag (only the ones the caller can see). Keyed under `tags`, so every tag write (rename, merge,
 * delete) refreshes the counts with the list.
 */
export const useTagUsage = () => {
  const client = useApiClient()
  const setupStore = useSetupStore()
  const query = useQuery({
    key: () => ['tags', 'usage', setupStore.state.organization?.id ?? null],
    query: async ({ signal }) => (await tagsUsage({ client, throwOnError: true, signal })).data,
    enabled: () => Boolean(setupStore.state.organization),
  })
  const counts = computed(
    () => new Map((query.data.value ?? []).map((row) => [row.tag_id, row.recordings_count] as const)),
  )
  // Undefined while loading, so rows do not flash «0».
  const countOf = (tagId: string) => (query.data.value ? (counts.value.get(tagId) ?? 0) : undefined)
  return { countOf, isLoading: query.isLoading }
}

export const recordingsCountLabel = (count: number) => pluralize(count, ['запись', 'записи', 'записей'])
