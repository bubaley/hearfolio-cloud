import {
  summaryTemplatesCreate,
  summaryTemplatesDestroy,
  summaryTemplatesList,
  summaryTemplatesPartialUpdate,
  summaryTemplatesRetrieve,
  type SummaryTemplateReadSchema,
} from '~/shared/api/generated'
import { defineResource } from '~/shared/api/resource'

export type SummaryTemplate = SummaryTemplateReadSchema
export type SummaryTemplateForm = { id: string | null; name: string; prompt: string; auto: boolean }

// Ordered by `position` on the server; members read, org admins write. Reordering patches `position` directly.
export const summaryTemplateResource = defineResource({
  key: 'summary-templates',
  sdk: {
    list: summaryTemplatesList,
    retrieve: summaryTemplatesRetrieve,
    create: summaryTemplatesCreate,
    update: summaryTemplatesPartialUpdate,
    destroy: summaryTemplatesDestroy,
  },
  toForm: (item?: Partial<SummaryTemplate>): SummaryTemplateForm => ({
    id: item?.id ?? null,
    name: item?.name ?? '',
    prompt: item?.prompt ?? '',
    auto: item?.auto ?? false,
  }),
  toCreate: (form) => {
    if (!form.name.trim()) throw new Error('Укажите название')
    if (!form.prompt.trim()) throw new Error('Опишите, что должно быть в саммари')
    return { name: form.name.trim(), prompt: form.prompt.trim(), auto: form.auto }
  },
  toUpdate: (form) => ({ name: form.name.trim(), prompt: form.prompt.trim(), auto: form.auto }),
})
