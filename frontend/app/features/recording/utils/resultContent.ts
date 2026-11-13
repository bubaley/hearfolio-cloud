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
