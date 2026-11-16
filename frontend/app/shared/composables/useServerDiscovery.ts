import { useQuery } from '@pinia/colada'
import { wellKnownHearfolio } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'

/**
 * `GET /.well-known/hearfolio`: the server's version, API version and limits. One request per page load: a redeploy
 * shows up after a reload.
 */
export const useServerDiscovery = () => {
  const client = useApiClient()
  return useQuery({
    key: ['server-discovery'],
    query: async ({ signal }) => (await wellKnownHearfolio({ client, throwOnError: true, signal })).data,
    staleTime: Number.POSITIVE_INFINITY,
  })
}
