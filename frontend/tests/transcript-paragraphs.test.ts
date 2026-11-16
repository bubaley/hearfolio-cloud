import { describe, expect, it } from 'vite-plus/test'
import {
  speakerHeading,
  speakerNames,
  transcriptParagraphs,
  transcriptPlainLines,
} from '~/features/recording/utils/transcriptParagraphs'

const seg = (start: number, end: number, text: string, speaker?: string | null) => ({
  start_ms: start * 1000,
  end_ms: end * 1000,
  text,
  ...(speaker === undefined ? {} : { speaker }),
})

describe('transcriptParagraphs', () => {
  it('joins one speaker with short pauses into one text', () => {
    const result = transcriptParagraphs([
      seg(0, 6, 'Вы хотите сэкономить передачу и разархивацию...'),
      seg(6, 12, 'Сколько секунд? Пять? Десять?'),
      seg(12, 18, 'Пять? Десять? Сколько секунд? В'),
    ])
    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({ start_ms: 0, end_ms: 18_000 })
    expect(result[0]!.text).toBe(
      'Вы хотите сэкономить передачу и разархивацию... Сколько секунд? Пять? Десять? Пять? Десять? Сколько секунд? В',
    )
  })

  it('splits on a speaker change, long pauses and the 90 s cap', () => {
    const result = transcriptParagraphs([
      seg(0, 1, 'Первый.', '0:0'),
      seg(1.5, 2, 'Ещё.', '0:0'),
      seg(2, 3, 'Второй.', '0:1'),
      // 2 s after a sentence end
      seg(5, 6, 'После паузы', '0:1'),
      // 3.9 s mid-sentence: same paragraph
      seg(9.9, 10, 'дальше', '0:1'),
      // 4 s mid-sentence: new paragraph
      seg(14, 15, 'и ещё', '0:1'),
    ])
    expect(result.map((p) => p.text)).toEqual(['Первый. Ещё.', 'Второй.', 'После паузы дальше', 'и ещё'])
    // Chunk-sized segments of models without timestamps stay as they are.
    expect(transcriptParagraphs([seg(0, 300, 'Часть один'), seg(300, 600, 'часть два')])).toHaveLength(2)
  })

  it('drops empty segments and leaves paragraphs untouched', () => {
    const paragraphs = [seg(0, 10, 'Абзац.', '0:0'), seg(10, 20, 'Другой.', '0:1')]
    expect(transcriptParagraphs([seg(0, 1, '  '), ...paragraphs])).toEqual(paragraphs)
  })
})

describe('speakerNames', () => {
  it('numbers comparable speakers in order of appearance', () => {
    const names = speakerNames([seg(0, 1, 'a', '0:1'), seg(1, 2, 'b', '0:0'), seg(2, 3, 'c', '0:1')])
    expect([...names]).toEqual([
      ['0:1', 'Спикер 1'],
      ['0:0', 'Спикер 2'],
    ])
    expect(transcriptPlainLines([seg(0, 1, 'Привет.', '0:1'), seg(1, 2, 'Хорошо.', '0:0')])).toEqual([
      'Спикер 1: Привет.',
      'Спикер 2: Хорошо.',
    ])
  })

  it('names nobody when there is one speaker or labels of several requests', () => {
    expect(speakerNames([seg(0, 1, 'a', '0:0'), seg(1, 2, 'b', '0:0')]).size).toBe(0)
    expect(speakerNames([seg(0, 1, 'a', '0:0'), seg(1, 2, 'b', '0:1'), seg(2, 3, 'c', '60000:0')]).size).toBe(0)
    expect(speakerNames([seg(0, 1, 'a'), seg(1, 2, 'b')]).size).toBe(0)
  })

  it('shows the name only where the speaker changes', () => {
    const segments = [seg(0, 1, 'a', '0:0'), seg(1, 2, 'b', '0:0'), seg(2, 3, 'c', '0:1')]
    const names = speakerNames(segments)
    expect(segments.map((_, index) => speakerHeading(segments, names, index))).toEqual([
      'Спикер 1',
      undefined,
      'Спикер 2',
    ])
  })
})
