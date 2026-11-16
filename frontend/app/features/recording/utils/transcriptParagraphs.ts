/**
 * Stored transcript segments shown as paragraphs: one speaker's continuous speech reads as one text. The server and
 * the app already build paragraphs with these rules (`ai/utils/transcript_phrases.py`, app `phrases.rs`); this joins
 * segments saved before that, which were single sentences. Applying it to paragraphs changes nothing.
 */
const SENTENCE_PAUSE_MS = 2000
const HARD_PAUSE_MS = 4000
const MAX_PARAGRAPH_MS = 90_000
const SENTENCE_END = /[.?!…]["'»”)\]]*$/

type Segment = { start_ms: number; end_ms: number; text: string; speaker?: string | null }

const endsSentence = (text: string) => SENTENCE_END.test(text.trimEnd())

export const transcriptParagraphs = <T extends Segment>(segments: readonly T[]): T[] => {
  const result: T[] = []
  for (const segment of segments) {
    const text = segment.text.trim()
    if (!text) continue
    const previous = result.at(-1)
    if (previous) {
      const pause = segment.start_ms - previous.end_ms
      const sameSpeaker = (previous.speaker ?? null) === (segment.speaker ?? null)
      const startsNew =
        !sameSpeaker ||
        pause >= HARD_PAUSE_MS ||
        (pause >= SENTENCE_PAUSE_MS && endsSentence(previous.text)) ||
        segment.end_ms - previous.start_ms > MAX_PARAGRAPH_MS
      if (!startsNew) {
        result[result.length - 1] = {
          ...previous,
          end_ms: Math.max(previous.end_ms, segment.end_ms),
          text: `${previous.text} ${text}`,
        }
        continue
      }
    }
    result.push({ ...segment, text })
  }
  return result
}
