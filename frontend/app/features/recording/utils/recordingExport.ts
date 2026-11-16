import type { RecordingResultReadSchema } from '~/shared/api/generated'
import type { RecordingDetail } from '../resources/recording'
import { speakerNames, transcriptParagraphs } from './transcriptParagraphs'

/** Transcript lines with timestamps, or the plain text when there are no segments. */
export const transcriptLines = (recording: RecordingDetail, timestamp: (clock: string) => string) => {
  if (!recording.transcript_segments.length) return [recording.transcript_text]
  const paragraphs = transcriptParagraphs(recording.transcript_segments)
  const names = speakerNames(paragraphs)
  return paragraphs.map((segment) => {
    const name = segment.speaker ? names.get(segment.speaker) : undefined
    return `${timestamp(formatClock(segment.start_ms))} ${name ? `${name}: ` : ''}${segment.text.trim()}`
  })
}

export const recordingToText = (recording: RecordingDetail, title: string) =>
  [title, '', ...transcriptLines(recording, (clock) => `[${clock}]`), ''].join('\n')

export const recordingToMarkdown = (
  recording: RecordingDetail,
  title: string,
  recordedAt: string,
  results: RecordingResultReadSchema[],
) => {
  const meta = [
    `- Дата: ${recordedAt}`,
    recording.duration_ms ? `- Длительность: ${formatDuration(recording.duration_ms)}` : '',
    recording.project ? `- Проект: ${recording.project.name}` : '',
    recording.tags.length ? `- Теги: ${recording.tags.map((tag) => tag.name).join(', ')}` : '',
  ].filter(Boolean)
  const summaries = results
    .filter((result) => result.status === 'done' && result.content.trim())
    .flatMap((result) => [`## ${result.title}`, '', result.content.trim(), ''])
  return [
    `# ${title}`,
    '',
    ...meta,
    '',
    ...summaries,
    '## Расшифровка',
    '',
    ...transcriptLines(recording, (clock) => `**${clock}**`).flatMap((line) => [line, '']),
  ].join('\n')
}

export const downloadText = (filename: string, content: string, type: string) => {
  const url = URL.createObjectURL(new Blob([content], { type: `${type};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** A file name from the title: no path separators or characters Windows rejects. */
export const safeFilename = (title: string) =>
  title
    .replace(/[\\/:*?"<>|\p{Cc}]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120) || 'Запись'
