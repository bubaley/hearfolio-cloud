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

/** Speaker names by label, as stored on a recording (found by the AI or set by a user). */
export type SpeakerNames = Record<string, string> | null | undefined

/**
 * The name to show for each stored speaker label: its stored name, else «Спикер N» (N in order of appearance); empty
 * when speakers are unknown or not comparable. Labels are scoped to one transcription request
 * (`<request start ms>:<id>`), so a transcript stitched from several requests, or with fewer than two speakers, gets
 * no names (same rule as the server's summaries).
 */
export const speakerNames = (segments: readonly Segment[], named?: SpeakerNames): Map<string, string> => {
  const labels = [...new Set(segments.filter((s) => s.text.trim() && s.speaker).map((s) => s.speaker as string))]
  const scopes = new Set(labels.map((label) => (label.includes(':') ? label.slice(0, label.lastIndexOf(':')) : '')))
  if (labels.length < 2 || scopes.size !== 1) return new Map()
  return new Map(labels.map((label, index) => [label, named?.[label]?.trim() || `Спикер ${index + 1}`]))
}

/** The name to show above a paragraph: only where the speaker changes. */
export const speakerHeading = (segments: readonly Segment[], names: Map<string, string>, index: number) => {
  const label = segments[index]?.speaker
  if (!label || !names.size) return undefined
  return index > 0 && segments[index - 1]?.speaker === label ? undefined : names.get(label)
}

/** Plain transcript lines, `Имя: …` where speakers are known. */
export const transcriptPlainLines = (segments: readonly Segment[], named?: SpeakerNames) => {
  const names = speakerNames(segments, named)
  return segments.map((segment) => {
    const name = segment.speaker ? names.get(segment.speaker) : undefined
    return name ? `${name}: ${segment.text}` : segment.text
  })
}
