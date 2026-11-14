import { describe, expect, it } from 'vite-plus/test'
import { fitTagChips } from '~/features/tag/composables/tagColors'

const tags = (...names: string[]) => names.map((name) => ({ name }))

describe('fitTagChips', () => {
  it('keeps every chip that fits the slot', () => {
    expect(fitTagChips(tags('Встреча', 'Обмен данными'), 13)).toHaveLength(2)
  })

  it('leaves room for «+N» when chips are hidden', () => {
    const fitted = fitTagChips(tags('Встреча', 'Клиент', 'Обмен данными', 'Срочно'), 13)
    expect(fitted.map((tag) => tag.name)).toEqual(['Встреча', 'Клиент'])
  })

  it('always shows the first chip, even a very long one', () => {
    expect(fitTagChips(tags('Очень длинное название тега для проверки', 'Клиент'), 13)).toHaveLength(1)
  })

  it('returns nothing for no tags', () => {
    expect(fitTagChips([], 13)).toEqual([])
  })
})
