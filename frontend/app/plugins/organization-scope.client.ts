import { useQueryCache } from '@pinia/colada'
import { resetQueryCache, SESSION_KEY, type Session } from '~/shared/composables/useSession'

/**
 * Query keys do not carry the organization: switching it must not show the previous organization's data. Drop
 * what is not on screen and refetch the rest with the new `Organization-Key` (the session is kept).
 */
export default defineNuxtPlugin(() => {
  const setupStore = useSetupStore()
  const queryCache = useQueryCache()
  watch(
    () => setupStore.state.organization?.id,
    (id, previous) => {
      if (!id || !previous || id === previous) return
      const session = queryCache.getQueryData([...SESSION_KEY]) as Session | null | undefined
      if (session) resetQueryCache(queryCache, session)
    },
  )
})
