import { useQuery } from '@pinia/colada'
import type { MaybeRefOrGetter } from 'vue'
import { aiSettingsUsage, recordingAiAiUsage } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'

/** What AI work on one recording cost (org admins only; members never request it). */
export const useRecordingAiUsage = (id: MaybeRefOrGetter<string>, enabled: MaybeRefOrGetter<boolean>) => {
  const client = useApiClient()
  return useQuery({
    key: () => ['recordings', toValue(id), 'ai-usage'],
    query: async ({ signal }) =>
      (await recordingAiAiUsage({ client, throwOnError: true, signal, path: { item_id: toValue(id) } })).data,
    enabled: () => toValue(enabled),
  })
}

/** Organization spending per user in [since, until) (org admins only). */
export const useOrganizationAiUsage = (
  period: MaybeRefOrGetter<{ since: Date; until: Date }>,
  enabled: MaybeRefOrGetter<boolean>,
) => {
  const client = useApiClient()
  return useQuery({
    key: () => ['ai-usage', toValue(period).since.toISOString(), toValue(period).until.toISOString()],
    query: async ({ signal }) => {
      const { since, until } = toValue(period)
      return (
        await aiSettingsUsage({
          client,
          throwOnError: true,
          signal,
          query: { since: since.toISOString(), until: until.toISOString() },
        })
      ).data
    },
    enabled: () => toValue(enabled),
  })
}
