import { useQueryCache } from '@pinia/colada'
import { createApiClient, type ApiError } from '~/shared/api/client'
import { SESSION_KEY } from '~/shared/composables/useSession'

/**
 * Provides `$api`, the generated client for this app instance (one per request on the server):
 * - browser: same-origin `/api/v1/...` (Caddy in production, the dev proxy in `nuxt dev`); on 401 it refreshes the
 *   session once and retries; a failed refresh signs out and sends app routes to `/auth`.
 * - SSR: `NUXT_API_INTERNAL_URL` with the incoming `cookie` header; only GETs run during SSR (CSRF contract).
 * Every request carries `Organization-Key` of the selected organization. A 403 `sso_required` («SSO only»
 * organization) sends the user to `/sso/<key>`.
 */
export default defineNuxtPlugin({
  name: 'api',
  setup(nuxtApp) {
    const config = useRuntimeConfig()
    const setupStore = useSetupStore()
    const router = useRouter()
    const cookie = import.meta.server ? useRequestHeaders(['cookie']).cookie : undefined

    let navigating = false
    router.beforeEach(() => {
      navigating = true
    })
    router.afterEach(() => {
      navigating = false
    })
    router.onError(() => {
      navigating = false
    })

    // A navigation in progress handles the missing session itself (route middleware redirects with `redirect`).
    const onSignedOut = () =>
      nuxtApp.runWithContext(() => {
        useQueryCache().setQueryData([...SESSION_KEY], null)
        const route = router.currentRoute.value
        if (navigating || route.meta.auth === false || route.meta.auth === 'guest') return
        void navigateTo({ name: 'auth', query: { redirect: route.fullPath } })
      })

    // An «SSO only» organization answers 403 `sso_required` to a session that did not come through its provider:
    // send the user through the provider and back to where they were.
    const onError = (error: ApiError) => {
      if (import.meta.server || error.status !== 403 || error.details?.reason !== 'sso_required') return
      const key = error.details.organization_key
      const route = router.currentRoute.value
      if (typeof key !== 'string' || route.name === 'sso-key' || navigating) return
      void nuxtApp.runWithContext(() =>
        navigateTo({ name: 'sso-key', params: { key }, query: { redirect: route.fullPath, required: '1' } }),
      )
    }

    const api = createApiClient({
      baseUrl: import.meta.server ? config.apiInternalUrl : '',
      refreshOnUnauthorized: import.meta.client,
      onSignedOut,
      onError,
      headers: () => ({ 'Organization-Key': setupStore.state.organization?.key, cookie }),
    })

    return { provide: { api } }
  },
})
