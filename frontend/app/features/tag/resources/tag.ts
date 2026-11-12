import {
  tagsCreate,
  tagsDestroy,
  tagsList,
  tagsPartialUpdate,
  tagsRetrieve,
  type TagColor,
  type TagReadSchema,
} from '~/shared/api/generated'
import { defineResource } from '~/shared/api/resource'

export type Tag = TagReadSchema
export type { TagColor }
export type TagForm = { id: string | null; name: string; color: TagColor | null }

export const tagResource = defineResource({
  key: 'tags',
  sdk: { list: tagsList, retrieve: tagsRetrieve, create: tagsCreate, update: tagsPartialUpdate, destroy: tagsDestroy },
  toForm: (item?: Partial<Tag>): TagForm => ({
    id: item?.id ?? null,
    name: item?.name ?? '',
    color: item?.color ?? null,
  }),
  toCreate: (form) => {
    const name = form.name.trim()
    if (!name) throw new Error('Введите название тега')
    // Without a color the server picks a stable one; an explicit null is a 500 there, so leave it out.
    return form.color ? { name, color: form.color } : { name }
  },
  toUpdate: (form) => (form.color ? { name: form.name.trim(), color: form.color } : { name: form.name.trim() }),
  // Recordings carry their tags (name and color).
  invalidates: ['recordings'],
})
