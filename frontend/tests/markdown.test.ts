import { describe, expect, it } from 'vite-plus/test'
import { parseInline, parseMarkdown, safeHref } from '../app/shared/lib/markdown'

describe('parseMarkdown', () => {
  it('parses headings, paragraphs, rules and code', () => {
    const blocks = parseMarkdown('# Итоги\n\nПервая строка\nвторая\n\n---\n\n```\n<b>code</b>\n```')
    expect(blocks.map((block) => block.type)).toEqual(['heading', 'paragraph', 'hr', 'code'])
    expect(blocks[1]).toEqual({
      type: 'paragraph',
      children: [{ type: 'text', text: 'Первая строка' }, { type: 'br' }, { type: 'text', text: 'вторая' }],
    })
    expect(blocks[3]).toEqual({ type: 'code', text: '<b>code</b>' })
  })

  it('parses ordered and nested lists', () => {
    const [list] = parseMarkdown('3. one\n4. two\n   - nested\n   - more')
    expect(list).toMatchObject({ type: 'list', ordered: true, start: 3 })
    if (list?.type !== 'list') throw new Error('not a list')
    expect(list.items).toHaveLength(2)
    expect(list.items[1]!.map((block) => block.type)).toEqual(['paragraph', 'list'])
  })

  it('parses quotes and tables', () => {
    const blocks = parseMarkdown('> цитата\n\n| Кто | Что |\n|---|:-:|\n| Аня | тексты |')
    expect(blocks[0]).toMatchObject({ type: 'quote', children: [{ type: 'paragraph' }] })
    expect(blocks[1]).toMatchObject({
      type: 'table',
      align: [null, 'center'],
      header: [[{ type: 'text', text: 'Кто' }], [{ type: 'text', text: 'Что' }]],
      rows: [[[{ type: 'text', text: 'Аня' }], [{ type: 'text', text: 'тексты' }]]],
    })
  })

  it('keeps raw HTML as text', () => {
    const blocks = parseMarkdown('<script>alert(1)</script> <img src=x onerror=alert(1)>')
    expect(blocks).toEqual([
      {
        type: 'paragraph',
        children: [{ type: 'text', text: '<script>alert(1)</script> <img src=x onerror=alert(1)>' }],
      },
    ])
  })
})

describe('parseInline', () => {
  it('parses marks', () => {
    expect(parseInline('**жирный** и *курсив*, `код`, ~~зачёркнутый~~')).toEqual([
      { type: 'strong', children: [{ type: 'text', text: 'жирный' }] },
      { type: 'text', text: ' и ' },
      { type: 'em', children: [{ type: 'text', text: 'курсив' }] },
      { type: 'text', text: ', ' },
      { type: 'code', text: 'код' },
      { type: 'text', text: ', ' },
      { type: 'del', children: [{ type: 'text', text: 'зачёркнутый' }] },
    ])
  })

  it('does not treat snake_case as emphasis', () => {
    expect(parseInline('user_id and file_name')).toEqual([{ type: 'text', text: 'user_id and file_name' }])
  })

  it('links only safe URLs', () => {
    expect(parseInline('[доска](https://example.com/a)')).toEqual([
      { type: 'link', href: 'https://example.com/a', children: [{ type: 'text', text: 'доска' }] },
    ])
    expect(parseInline('[плохая](javascript:alert(1))')).toEqual([{ type: 'text', text: 'плохая' }])
    expect(parseInline('см. https://example.com/x.')).toEqual([
      { type: 'text', text: 'см. ' },
      { type: 'link', href: 'https://example.com/x', children: [{ type: 'text', text: 'https://example.com/x' }] },
      { type: 'text', text: '.' },
    ])
  })

  it('accepts only http(s) and mailto hrefs', () => {
    expect(safeHref(' https://a.b ')).toBe('https://a.b')
    expect(safeHref('mailto:a@b.c')).toBe('mailto:a@b.c')
    expect(safeHref('data:text/html,x')).toBeNull()
    expect(safeHref('/relative')).toBeNull()
  })
})
