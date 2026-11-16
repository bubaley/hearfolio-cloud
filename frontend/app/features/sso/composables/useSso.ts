import { useMutation, useQuery, useQueryCache } from '@pinia/colada'
import {
  ssoIdentities,
  ssoLink,
  ssoProviderCurrent,
  ssoProviderDestroyCurrent,
  ssoProviderTestConnection,
  ssoProviderUpdateCurrent,
  ssoStart,
  ssoUnlink,
  type SsoConnectionTestSchema,
  type SsoJoinPolicy,
  type SsoLoginMode,
  type SsoProviderUpdateSchema,
  type SsoStartSchema,
} from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { useApiClient } from '~/shared/api/useResource'

/** `GET/PATCH/DELETE /sso-provider/current` of the selected organization (a singleton, not a CRUD resource). */
const SSO_SETTINGS_KEY = ['sso-provider', 'current'] as const
const SSO_IDENTITIES_KEY = ['sso', 'identities'] as const

/** Russian text for an SSO API error: the backend already words provider and rule errors in Russian. */
export const ssoErrorMessage = (error: unknown, fallback: string) => {
  if (isApiError(error, 403)) return 'Настройки входа доступны владельцам и администраторам'
  if (isApiError(error, 422)) return `${fallback}: проверьте значения`
  if (isApiError(error) && error.status >= 400 && error.status < 500 && error.message) return error.message
  return fallback
}

/** Why a sign-in through the provider failed: `?sso_error=<reason>` after the callback redirect. */
const SSO_ERROR_MESSAGES: Record<string, string> = {
  invalid_state: 'Вход устарел или уже завершён. Начните заново',
  browser_mismatch: 'Вход начат в другом браузере. Начните заново в этом',
  provider_denied: 'Вход отменён у провайдера',
  provider_error: 'Провайдер не подтвердил вход',
  not_member: 'Вы не участник этой организации. Попросите приглашение у администратора',
  domain_not_allowed: 'Вход разрешён только с подтверждённой почтой разрешённого домена',
  group_required: 'У вас нет нужной группы у провайдера. Обратитесь к администратору',
  email_not_verified:
    'Провайдер не подтвердил вашу почту, поэтому вход нельзя связать с аккаунтом. Войдите по паролю и привяжите провайдера в профиле',
  email_required: 'Провайдер не сообщил почту: администратору нужно добавить scope email',
  email_taken: 'Аккаунт с этой почтой уже существует. Войдите по паролю',
  email_invalid: 'Провайдер сообщил почту, которую Hearfolio не принимает',
  identity_conflict: 'К аккаунту уже привязан другой аккаунт этого провайдера. Сначала отвяжите его',
  identity_taken: 'Этот аккаунт провайдера уже привязан к другому пользователю',
  user_inactive: 'Аккаунт отключён. Обратитесь к администратору',
  token_error: 'Провайдер отклонил вход. Проверьте настройки подключения',
  provider_unavailable: 'Провайдер недоступен. Попробуйте позже',
}

export const ssoCallbackErrorMessage = (reason: unknown) =>
  typeof reason === 'string' && reason
    ? (SSO_ERROR_MESSAGES[reason] ?? 'Не удалось войти через SSO. Если повторится — сообщите администратору')
    : null

export const LOGIN_MODE_OPTIONS: { value: SsoLoginMode; label: string }[] = [
  { value: 'password_and_sso', label: 'Пароль или SSO' },
  { value: 'sso_only', label: 'Только SSO' },
]

export const JOIN_POLICY_OPTIONS: { value: SsoJoinPolicy; label: string }[] = [
  { value: 'invite_only', label: 'Только по приглашению' },
  { value: 'provider', label: 'Любой, кого пустит провайдер' },
]

export const REVALIDATE_OPTIONS = [5, 10, 15, 30, 60].map((value) => ({
  value,
  label: `Каждые ${value} мин${value === 10 ? ' (рекомендуется)' : ''}`,
}))

/** «a, b c» → ['a', 'b', 'c'] */
export const splitList = (value: string) =>
  value
    .split(/[\s,;]+/)
    .map((item) => item.trim())
    .filter(Boolean)

/** Same-site organization choice after a sign-in started from `/sso/<key>` (read by `useSetupStore.restore`). */
export const PREFERRED_ORGANIZATION_KEY = 'setup:prefer-organization'

export const useSsoSettings = (options: { enabled?: () => boolean } = {}) => {
  const client = useApiClient()
  const queryCache = useQueryCache()
  const query = useQuery({
    key: [...SSO_SETTINGS_KEY],
    query: async ({ signal }) => (await ssoProviderCurrent({ client, throwOnError: true, signal })).data,
    enabled: () => options.enabled?.() ?? true,
  })
  const update = useMutation({
    mutation: async (body: SsoProviderUpdateSchema) =>
      (await ssoProviderUpdateCurrent({ client, throwOnError: true, body })).data,
    onSuccess: (data) => queryCache.setQueryData([...SSO_SETTINGS_KEY], data),
  })
  const remove = useMutation({
    mutation: async () => {
      await ssoProviderDestroyCurrent({ client, throwOnError: true })
    },
    onSettled: () => {
      void queryCache.invalidateQueries({ key: [...SSO_SETTINGS_KEY] }).catch(() => undefined)
    },
  })
  const testConnection = (body: SsoConnectionTestSchema) =>
    ssoProviderTestConnection({ client, throwOnError: true, body }).then(({ data }) => data)

  return { settings: query.data, query, update, remove, testConnection }
}

/** Leave for the provider: the browser must navigate (the provider shows its own sign-in page). */
export const useSsoStart = () => {
  const client = useApiClient()
  const start = async (body: SsoStartSchema) => {
    const { data } = await ssoStart({ client, throwOnError: true, body })
    if (body.organization_key) {
      try {
        sessionStorage.setItem(PREFERRED_ORGANIZATION_KEY, body.organization_key)
      } catch {
        // Private mode: the organization choice simply falls back to the usual rules.
      }
    }
    window.location.assign(data.authorization_url)
  }
  return { start }
}

export const useSsoIdentities = () => {
  const client = useApiClient()
  const queryCache = useQueryCache()
  const query = useQuery({
    key: [...SSO_IDENTITIES_KEY],
    query: async ({ signal }) => (await ssoIdentities({ client, throwOnError: true, signal })).data,
  })
  const unlink = useMutation({
    mutation: async (identity: string) => {
      await ssoUnlink({ client, throwOnError: true, path: { identity } })
    },
    onSettled: () => {
      void queryCache.invalidateQueries({ key: [...SSO_IDENTITIES_KEY] }).catch(() => undefined)
    },
  })
  const link = async (organizationKey: string) => {
    const { data } = await ssoLink({
      client,
      throwOnError: true,
      body: { organization_key: organizationKey, redirect: '/settings/profile' },
    })
    window.location.assign(data.authorization_url)
  }
  return { identities: query.data, query, unlink, link }
}
