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
export type SummaryTemplateForm = {
  id: string | null
  name: string
  description: string
  prompt: string
  auto: boolean
}

/** `SummaryTemplate.description` limit on the server. */
export const TEMPLATE_DESCRIPTION_MAX = 200

/**
 * The one line pickers show under a template's name: its `description`, else the first sentence of the prompt without
 * technical asides such as «(«- [ ] задача»)» or «Markdown».
 */
export const templateDescription = (template: Pick<SummaryTemplate, 'prompt'> & { description?: string | null }) => {
  const own = template.description?.trim()
  if (own) return own
  const sentence = /^[^.!?\n]+/.exec(template.prompt.trim())?.[0] ?? ''
  const cleaned = sentence
    .replace(/\s*\([^)]*\)/g, '')
    .replace(/\s*Markdown/gi, '')
    .replace(/\s+/g, ' ')
    .replace(/[\s,:;—-]+$/, '')
    .trim()
  return cleaned ? cleaned[0]!.toLocaleUpperCase('ru') + cleaned.slice(1) : ''
}

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
    description: item?.description ?? '',
    prompt: item?.prompt ?? '',
    auto: item?.auto ?? false,
  }),
  toCreate: (form) => {
    if (!form.name.trim()) throw new Error('Укажите название')
    if (!form.prompt.trim()) throw new Error('Опишите, что должно быть в саммари')
    return {
      name: form.name.trim(),
      description: form.description.trim(),
      prompt: form.prompt.trim(),
      auto: form.auto,
    }
  },
  toUpdate: (form) => ({
    name: form.name.trim(),
    description: form.description.trim(),
    prompt: form.prompt.trim(),
    auto: form.auto,
  }),
})
