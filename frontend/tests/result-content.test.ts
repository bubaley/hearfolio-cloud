import { describe, expect, it } from 'vite-plus/test'
import { stripLeadingTitle, templateDescription } from '../app/features/recording/utils/resultContent'

describe('stripLeadingTitle', () => {
  it('drops a leading heading that repeats the title', () => {
    expect(stripLeadingTitle('## Кратко\n\nКоманда обсудила сроки', 'Кратко')).toBe('Команда обсудила сроки')
    expect(stripLeadingTitle('# «Решения и договорённости»:\nТекст', 'Решения и договорённости')).toBe('Текст')
  })

  it('keeps other headings and plain text', () => {
    expect(stripLeadingTitle('## Решения\n- пункт', 'Кратко')).toBe('## Решения\n- пункт')
    expect(stripLeadingTitle('Кратко\nтекст', 'Кратко')).toBe('Кратко\nтекст')
  })
})

describe('templateDescription', () => {
  it('takes the first sentence without technical asides', () => {
    expect(templateDescription('Кратко перескажи запись. Сначала одна-две фразы')).toBe('Кратко перескажи запись')
    expect(
      templateDescription('составь список задач из записи в виде чек-листа Markdown («- [ ] задача»). Для каждой'),
    ).toBe('Составь список задач из записи в виде чек-листа')
  })
})
