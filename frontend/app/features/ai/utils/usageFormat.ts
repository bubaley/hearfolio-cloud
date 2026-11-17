/** Money and amounts of AI spending, as the provider reported them (USD). */

/** `$0.05`, `$0.0012` for small sums (two significant digits), `$0` for nothing. */
export const formatUsd = (value: number | null | undefined) => {
  if (!value) return '$0'
  if (value >= 1) return `$${value.toFixed(2)}`
  const digits = Math.min(6, Math.max(2, 1 - Math.floor(Math.log10(value))))
  return `$${value.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '')}`
}

/** `850`, `12,3 тыс.`, `1,2 млн` tokens. */
export const formatTokens = (value: number) => {
  if (value < 1000) return String(value)
  if (value < 1_000_000) return `${(value / 1000).toLocaleString('ru', { maximumFractionDigits: 1 })} тыс.`
  return `${(value / 1_000_000).toLocaleString('ru', { maximumFractionDigits: 1 })} млн`
}

/** `45 сек`, `32 мин`, `1 ч 05 мин` of audio. */
export const formatAudio = (ms: number) => {
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds} сек`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} мин`
  return `${Math.floor(minutes / 60)} ч ${String(minutes % 60).padStart(2, '0')} мин`
}
