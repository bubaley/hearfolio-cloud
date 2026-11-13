import { toCalendarDate } from '@internationalized/date'
import type { MaybeRefOrGetter } from 'vue'
import { formatDatePattern } from '~/shared/lib/dateFormat'
import type { Recording } from '../resources/recording'

export type RecordingGroup = { key: string; label: string; rows: { recording: Recording; time: string }[] }

/** Rows grouped by local day of `recorded_at` (newest first, as the API sorts): «Сегодня», «Вчера», «12 ноября». */
export const useRecordingGroups = (items: MaybeRefOrGetter<Recording[]>) => {
  const { parseDate, now } = useDate()
  return computed<RecordingGroup[]>(() => {
    const today = toCalendarDate(now('date'))
    const groups: RecordingGroup[] = []
    for (const recording of toValue(items)) {
      const date = parseDate(recording.recorded_at)
      if (!date) continue
      const day = toCalendarDate(date)
      const key = day.toString()
      let group = groups.at(-1)
      if (group?.key !== key) {
        const diff = day.compare(today)
        const label =
          diff === 0
            ? 'Сегодня'
            : diff === -1
              ? 'Вчера'
              : formatDatePattern(date, day.year === today.year ? 'D MMMM' : 'D MMMM YYYY')
        group = { key, label, rows: [] }
        groups.push(group)
      }
      group.rows.push({ recording, time: formatDatePattern(date, 'HH:mm') })
    }
    return groups
  })
}
