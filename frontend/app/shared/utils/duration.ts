/** `4:05` or `1:02:03` for a player, a list row or a transcript timestamp. */
export const formatClock = (ms: number) => {
  const total = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = String(total % 60).padStart(2, '0')
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`
}

/** `40 сек`, `12 мин`, `1 ч 5 мин`: a duration in a sentence or a property. */
export const formatDuration = (ms: number) => {
  const total = Math.round(ms / 1000)
  if (total < 60) return `${total} сек`
  const minutes = Math.round(total / 60)
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`
}
