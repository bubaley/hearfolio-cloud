import { useMutation, useQuery, useQueryCache } from '@pinia/colada'
import {
  aiSettingsCurrent,
  aiSettingsModels,
  aiSettingsTestConnection,
  aiSettingsUpdateCurrent,
  type AiConnectionTestSchema,
  type AiModelKind,
  type AiModelSchema,
  type OrganizationSettingsUpdateSchema,
} from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { useApiClient } from '~/shared/api/useResource'
import type { SelectSource } from '~/shared/ui/app/select/types'

export type AiSettingsPatch = OrganizationSettingsUpdateSchema
export type AiModel = AiModelSchema

/** `GET/PATCH /ai-settings/current` of the selected organization (a singleton, not a CRUD resource). */
const AI_SETTINGS_KEY = ['ai-settings', 'current'] as const

/** Russian text for an AI settings error: provider errors already carry one, validation errors do not. */
export const aiErrorMessage = (error: unknown, fallback: string) => {
  if (isApiError(error, 403)) return 'Настройки AI доступны владельцам и администраторам'
  if (isApiError(error) && error.details?.ai_error) return error.message
  if (isApiError(error, 400) || isApiError(error, 422)) return `${fallback}: проверьте значения`
  return fallback
}

export const useAiSettings = (options: { enabled?: () => boolean } = {}) => {
  const client = useApiClient()
  const queryCache = useQueryCache()
  const query = useQuery({
    key: [...AI_SETTINGS_KEY],
    query: async ({ signal }) => (await aiSettingsCurrent({ client, throwOnError: true, signal })).data,
    enabled: () => options.enabled?.() ?? true,
  })
  const update = useMutation({
    mutation: async (body: AiSettingsPatch) =>
      (await aiSettingsUpdateCurrent({ client, throwOnError: true, body })).data,
    onSuccess: (data) => {
      queryCache.setQueryData([...AI_SETTINGS_KEY], data)
      // Members' pickers read `/ai-settings/options`.
      void queryCache.invalidateQueries({ key: ['ai-options'] })
    },
  })
  const testConnection = (body: AiConnectionTestSchema) =>
    aiSettingsTestConnection({ client, throwOnError: true, body }).then(({ data }) => data)

  return { settings: query.data, query, update, testConnection }
}

/** Provider catalog for `AppSelect`: one cached request per search, no pagination. */
export const aiModelSource = (kind: AiModelKind): SelectSource<AiModel> => {
  const client = useApiClient()
  return {
    list: async (query) => {
      const search = typeof query.search === 'string' && query.search ? query.search : undefined
      const { data } = await aiSettingsModels({ client, throwOnError: true, query: { kind, search } })
      return { items: data, hasNext: false }
    },
  }
}
