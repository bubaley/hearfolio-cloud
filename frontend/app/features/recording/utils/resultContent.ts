const comparable = (value: string) =>
  value
    .toLocaleLowerCase('ru')
    .replace(/[*_`«»"'“”.:!?]/g, '')
    .replace(/\s+/g, ' ')
    .trim()

/**
 * Summary Markdown without a leading heading that repeats the card title (models often start with `# Кратко`), so the
 * card does not say its name twice. Other headings stay.
 */
export const stripLeadingTitle = (content: string, title: string) => {
  const match = /^\s*#{1,3}\s+(.+?)\s*#*\s*(?:\n|$)/.exec(content)
  if (!match || comparable(match[1]!) !== comparable(title)) return content
  return content.slice(match[0].length).replace(/^\s*\n/, '')
}

/**
 * A short human description of a summary template from its prompt (there is no description field): the first sentence
 * without technical asides such as «(«- [ ] задача»)» or «Markdown».
 */
export const templateDescription = (prompt: string) => {
  const sentence = /^[^.!?\n]+/.exec(prompt.trim())?.[0] ?? ''
  const cleaned = sentence
    .replace(/\s*\([^)]*\)/g, '')
    .replace(/\s*Markdown/gi, '')
    .replace(/\s+/g, ' ')
    .replace(/[\s,:;—-]+$/, '')
    .trim()
  return cleaned ? cleaned[0]!.toLocaleUpperCase('ru') + cleaned.slice(1) : ''
}
