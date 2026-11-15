import { ensureSession } from '~/shared/composables/useSession'

/**
 * The landing page is for visitors: a signed-in user opening the site root goes straight to the recordings. On the
 * server this uses the visitor's cookie (a 302); when only the refresh cookie is left, the client check catches it.
 */
export default defineNuxtRouteMiddleware(async () => {
  if (await ensureSession()) return navigateTo({ name: 'recordings' }, { replace: true })
})
