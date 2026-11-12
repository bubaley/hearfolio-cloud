import { CircleCheck, CircleDashed, Clock, Link2, Ban } from '@lucide/vue'
import type { InviteState } from '~/shared/api/generated'
import type { AppLabelConfig } from '~/shared/ui/app/types/label-types'

export const INVITE_STATE_LABELS: Record<InviteState, AppLabelConfig> = {
  valid: { label: 'Активно', icon: Link2, tone: 'success' },
  used: { label: 'Принято', icon: CircleCheck, tone: 'muted' },
  expired: { label: 'Истекло', icon: Clock, tone: 'warning' },
  revoked: { label: 'Отозвано', icon: Ban, tone: 'muted' },
}

export const INVITE_EXPIRY_OPTIONS = [
  { label: '1 день', value: 1 },
  { label: '3 дня', value: 3 },
  { label: '7 дней', value: 7 },
  { label: '14 дней', value: 14 },
  { label: '30 дней', value: 30 },
]

export const getInviteStateLabel = (state: InviteState | null | undefined) =>
  state ? INVITE_STATE_LABELS[state] : { label: 'Неизвестно', icon: CircleDashed, tone: 'muted' as const }
