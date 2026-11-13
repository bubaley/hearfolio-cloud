import type { AiOptionsSchema } from '~/shared/api/generated'

/** What happens to a recording after its audio reaches the server, from `/ai-settings/options`. */
export type ProcessingMode = 'unknown' | 'not_configured' | 'manual' | 'auto'

export const processingMode = (options: AiOptionsSchema | undefined): ProcessingMode => {
  if (!options) return 'unknown'
  if (!options.configured) return 'not_configured'
  return options.auto_transcribe ? 'auto' : 'manual'
}

const joinRu = (parts: string[]) =>
  parts.length > 1 ? `${parts.slice(0, -1).join(', ')} и ${parts.at(-1)}` : (parts[0] ?? '')

/** «текст, название и теги»: what the automatic pipeline produces with the organization's switches. */
const autoOutputs = (options: AiOptionsSchema) =>
  joinRu(['текст', ...(options.auto_title ? ['название'] : []), ...(options.auto_tags ? ['теги'] : [])])

/** The «Загрузить запись» dialog subtitle. */
export const uploadHint = (options: AiOptionsSchema | undefined, isAdmin: boolean) => {
  switch (processingMode(options)) {
    case 'not_configured':
      return isAdmin
        ? 'Файл сохранится сразу. Расшифровка начнётся, когда вы подключите AI в «AI и модели»'
        : 'Файл сохранится сразу. Расшифровка начнётся, когда администратор подключит AI'
    case 'manual':
      return 'Файл сохранится сразу. Автоматическая расшифровка в организации выключена — её можно запустить на странице записи'
    case 'auto':
      return `Файл сохранится сразу, а ${autoOutputs(options!)} появятся через пару минут после загрузки`
    default:
      return 'Файл сохранится сразу'
  }
}

/** The upload tray once every file is uploaded. */
export const uploadDoneHint = (options: AiOptionsSchema | undefined) => {
  switch (processingMode(options)) {
    case 'not_configured':
      return 'Расшифровка начнётся, когда подключат AI'
    case 'manual':
      return 'Расшифровку можно запустить на странице записи'
    case 'auto':
      return 'Расшифровка уже началась'
    default:
      return 'Записи сохранены'
  }
}

/** The «Аудио загружается» notice on a recording page. */
export const awaitingUploadHint = (options: AiOptionsSchema | undefined) => {
  switch (processingMode(options)) {
    case 'not_configured':
      return 'Когда файл дойдёт до сервера, он сохранится; расшифровка начнётся после подключения AI'
    case 'manual':
      return 'Когда файл дойдёт до сервера, запись можно будет расшифровать — автоматическая расшифровка выключена'
    case 'auto':
      return 'Когда файл дойдёт до сервера, запись сразу встанет в очередь на расшифровку'
    default:
      return 'Когда файл дойдёт до сервера, запись появится здесь целиком'
  }
}
