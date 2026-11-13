import type { Component } from 'vue'

/** An action of the ⌘K palette. */
export type PaletteCommand = {
  id: string
  label: string
  icon: Component
  /** Extra words the filter matches («share», «ссылка»). */
  keywords?: string
  destructive?: boolean
  run: () => void
}

// Commands of the open screen (the recording page: share, copy, delete). Client-only state: the workspace is an SPA.
const pageCommands = shallowRef<{ title: string; commands: PaletteCommand[] } | null>(null)

/** Open state of the ⌘K palette, shared by the sidebar «Поиск» item, the phone top bar and the keyboard shortcut. */
export const useQuickSearch = () => {
  const open = useState('recording-quick-search', () => false)
  return {
    open,
    pageCommands: computed(() => pageCommands.value),
    show: () => {
      open.value = true
    },
  }
}

/** A screen offers its own actions in the palette while it is mounted. */
export const usePageCommands = (source: () => { title: string; commands: PaletteCommand[] } | null) => {
  let stop: (() => void) | undefined
  // Started on mount: the source may read state the screen declares further down in its setup.
  onMounted(() => {
    stop = watchEffect(() => {
      pageCommands.value = source()
    })
  })
  onBeforeUnmount(() => {
    stop?.()
    pageCommands.value = null
  })
}

type RecentRecording = { id: string; title: string }
const RECENT_LIMIT = 8

/**
 * Recordings the user actually opened, newest first and deduplicated, per organization and browser (localStorage).
 * The palette shows them as «Недавние».
 */
export const useRecentRecordings = () => {
  const setupStore = useSetupStore()
  const key = computed(() => `hearfolio:recent-recordings:${setupStore.state.organization?.id ?? 'none'}`)
  const read = (): RecentRecording[] => {
    try {
      const value = JSON.parse(localStorage.getItem(key.value) ?? '[]')
      return Array.isArray(value)
        ? value.filter(
            (item): item is RecentRecording => typeof item?.id === 'string' && typeof item.title === 'string',
          )
        : []
    } catch {
      return []
    }
  }
  const write = (items: RecentRecording[]) => {
    try {
      localStorage.setItem(key.value, JSON.stringify(items.slice(0, RECENT_LIMIT)))
    } catch {
      // Private mode or full storage: recents are a convenience.
    }
  }
  return {
    list: read,
    remember: (item: RecentRecording) => write([item, ...read().filter((recent) => recent.id !== item.id)]),
    forget: (id: string) => write(read().filter((recent) => recent.id !== id)),
  }
}
