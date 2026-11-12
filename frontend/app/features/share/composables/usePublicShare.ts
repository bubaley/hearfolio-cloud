import { useQuery } from '@pinia/colada'
import { isApiError } from '~/shared/api/client'
import { publicShareRetrieve, type PublicShareSchema } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'

export type PublicShare = PublicShareSchema
/** A summary exposed by a share link (`results` come from the ai domain, see product.md → ShareLink). */
export type PublicShareResult = { id: string; title: string; content: string; created_at?: string }

/**
 * `GET /public/share/{token}`, fetched during SSR and hydrated from the payload. `null` = the link is unknown,
 * revoked or expired (404); the server response is then a 404 too. Other errors stay errors (retry).
 */
export const usePublicShare = (token: MaybeRefOrGetter<string>) => {
  const client = useApiClient()
  const event = import.meta.server ? useRequestEvent() : undefined
  return useQuery({
    key: () => ['public-share', toValue(token)],
    query: async ({ signal }): Promise<PublicShare | null> => {
      try {
        return (await publicShareRetrieve({ client, throwOnError: true, signal, path: { token: toValue(token) } })).data
      } catch (error) {
        if (!isApiError(error, 404)) throw error
        if (event) setResponseStatus(event, 404)
        return null
      }
    },
    // A failed SSR fetch renders the error state instead of the Nuxt error page.
    ssrCatchError: true,
    // Every open counts a view; the page refetches only when the audio URL runs out.
    staleTime: Infinity,
  })
}

export const shareResults = (share: PublicShare | null | undefined): PublicShareResult[] =>
  (share?.results ?? []).flatMap((raw) => {
    const { id, title, content, created_at } = raw as Record<string, unknown>
    if (typeof id !== 'string' || typeof content !== 'string') return []
    return [
      {
        id,
        title: typeof title === 'string' && title ? title : 'Саммари',
        content,
        created_at: typeof created_at === 'string' ? created_at : undefined,
      },
    ]
  })

/** `4:05` or `1:02:03` for a player or a transcript timestamp. */
export const formatClock = (ms: number) => {
  const total = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = String(total % 60).padStart(2, '0')
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`
}

/** `40 сек`, `12 мин`, `1 ч 5 мин`. */
export const formatDuration = (ms: number) => {
  const total = Math.round(ms / 1000)
  if (total < 60) return `${total} сек`
  const minutes = Math.round(total / 60)
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`
}
