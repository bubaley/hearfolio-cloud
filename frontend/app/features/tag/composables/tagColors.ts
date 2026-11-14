import { isApiError } from '~/shared/api/client'
import type { TagColor } from '../resources/tag'

/** The tag palette in display order with Russian names. Chip classes use the `tag-*` tokens from theme.css. */
export const TAG_COLORS: { value: TagColor; label: string; chip: string }[] = [
  { value: 'gray', label: 'Серый', chip: 'bg-tag-gray text-tag-gray-foreground' },
  { value: 'brown', label: 'Коричневый', chip: 'bg-tag-brown text-tag-brown-foreground' },
  { value: 'orange', label: 'Оранжевый', chip: 'bg-tag-orange text-tag-orange-foreground' },
  { value: 'yellow', label: 'Жёлтый', chip: 'bg-tag-yellow text-tag-yellow-foreground' },
  { value: 'green', label: 'Зелёный', chip: 'bg-tag-green text-tag-green-foreground' },
  { value: 'blue', label: 'Синий', chip: 'bg-tag-blue text-tag-blue-foreground' },
  { value: 'purple', label: 'Фиолетовый', chip: 'bg-tag-purple text-tag-purple-foreground' },
  { value: 'pink', label: 'Розовый', chip: 'bg-tag-pink text-tag-pink-foreground' },
  { value: 'red', label: 'Красный', chip: 'bg-tag-red text-tag-red-foreground' },
]

export const tagChipClass = (color: TagColor | null | undefined) =>
  (TAG_COLORS.find((item) => item.value === color) ?? TAG_COLORS[0]!).chip

/** Russian text for tag API errors. */
export const tagErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error && !isApiError(error) && error.message) return error.message
  if (isApiError(error, 403)) return 'Менять, объединять и удалять теги могут только администраторы'
  if (isApiError(error, 409)) return 'Тег с таким названием уже есть'
  if (isApiError(error, 404)) return 'Тег не найден — возможно, его уже удалили'
  if (isApiError(error, 422) || isApiError(error, 400)) return 'Проверьте название тега'
  return fallback
}

/**
 * How many whole chips fit a fixed-width slot (`budget` in rem); the rest collapse into «+N». The width comes from
 * the text length, not the DOM: the same answer on the server and the client, no measuring per row, and rows never
 * show a chip cut in half. The first chip always shows (a very long name truncates inside the slot).
 */
export const fitTagChips = <T extends { name: string }>(tags: T[], budget: number): T[] => {
  // text-xs chip: 0.75rem of padding, ~0.44rem per character; 0.25rem gap; «+N» takes ~1.6rem.
  const GAP = 0.25
  const COUNTER = 1.6
  const width = (tag: T) => 0.75 + tag.name.length * 0.44
  const fitted: T[] = []
  let used = 0
  for (const [index, tag] of tags.entries()) {
    const next = used + (fitted.length ? GAP : 0) + width(tag)
    const rest = tags.length - index - 1
    if (fitted.length && next + (rest ? GAP + COUNTER : 0) > budget) break
    fitted.push(tag)
    used = next
  }
  return fitted
}
