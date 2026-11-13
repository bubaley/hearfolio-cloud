/**
 * One-time welcome after joining by invite. Kept per user in localStorage: `pending` is set when the invite is
 * accepted, the shell shows the welcome once and stores `done`. Storage can be unavailable (private mode, blocked site
 * data); then the welcome simply does not show.
 */
const storageKey = (userId: string) => `hearfolio:welcome:${userId}`

const read = (userId: string): string | null => {
  try {
    return window.localStorage.getItem(storageKey(userId))
  } catch {
    return null
  }
}

const write = (userId: string, value: 'pending' | 'done') => {
  try {
    window.localStorage.setItem(storageKey(userId), value)
  } catch {
    // Not remembered: at worst the welcome does not show, or shows once more.
  }
}

/** After an invite is accepted. A user who already dismissed it once is not welcomed again. */
export const markWelcomePending = (userId: string) => {
  if (read(userId) !== 'done') write(userId, 'pending')
}

export const isWelcomePending = (userId: string) => read(userId) === 'pending'

export const dismissWelcome = (userId: string) => write(userId, 'done')
