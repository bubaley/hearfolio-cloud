import { isApiError } from '~/shared/api/client'

// Russian text for `details.reason` of organization, membership and invite errors (backend messages are English).
const REASON_MESSAGES: Record<string, string> = {
  last_owner: 'В организации должен остаться хотя бы один владелец. Сначала назначьте другого владельца',
  not_admin: 'Это могут сделать только владельцы и администраторы',
  not_owner: 'Это может сделать только владелец организации',
  already_member: 'Пользователь уже состоит в организации',
  invite_not_found: 'Приглашение не найдено. Проверьте ссылку',
  invite_expired: 'Срок действия приглашения истёк',
  invite_used: 'Приглашение уже использовано',
  invite_revoked: 'Приглашение отозвано',
  email_exists: 'Этот email уже зарегистрирован. Войдите, чтобы принять приглашение',
  registration_required: 'Войдите или зарегистрируйтесь, чтобы принять приглашение',
}

/** `details.reason` of an API error, if any. */
export const apiErrorReason = (error: unknown): string | null => {
  if (!isApiError(error)) return null
  const reason = error.details?.reason
  return typeof reason === 'string' ? reason : null
}

/** A Russian message for an organization-domain API error, or `fallback`. */
export const organizationErrorMessage = (error: unknown, fallback: string): string => {
  const reason = apiErrorReason(error)
  if (reason && REASON_MESSAGES[reason]) return REASON_MESSAGES[reason]
  if (isApiError(error, 429)) return 'Слишком много попыток. Попробуйте позже'
  if (isApiError(error, 403)) return 'Недостаточно прав'
  return fallback
}
