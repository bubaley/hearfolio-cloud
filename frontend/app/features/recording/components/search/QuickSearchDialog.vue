<template>
  <!-- No closing animation on the content: Reka keeps `pointer-events: none` on <body> until the dialog unmounts,
       so a click right after Escape would be swallowed by a fading palette. -->
  <AppModal
    v-model="open"
    title="Поиск и команды"
    hide-title
    width="36rem"
    content-class="top-[12vh] translate-y-0 gap-0 overflow-hidden p-0 data-[state=closed]:animate-none sm:top-[15vh]"
    :closeable="false"
  >
    <div
      class="flex flex-col"
      @keydown="onKeydown"
    >
      <div class="flex items-center gap-2 border-b border-border px-4">
        <AppIcon
          :icon="Search"
          size="md"
          class="shrink-0 text-muted-foreground"
        />
        <input
          ref="input"
          v-model="query"
          type="search"
          autocomplete="off"
          placeholder="Найти запись, проект или команду…"
          aria-label="Поиск записей, проектов и команд"
          role="combobox"
          aria-expanded="true"
          aria-controls="quick-search-results"
          :aria-activedescendant="flat[active] ? optionId(flat[active]!) : undefined"
          class="h-13 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground"
        />
        <AppIcon
          v-if="isFetching"
          loading
          size="sm"
          class="shrink-0 text-muted-foreground"
        />
        <kbd class="hidden shrink-0 rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground sm:inline"
          >Esc</kbd
        >
      </div>

      <div
        id="quick-search-results"
        role="listbox"
        aria-label="Результаты"
        class="max-h-[min(28rem,60dvh)] overflow-y-auto p-1.5"
      >
        <div
          v-for="group in groups"
          :key="group.key"
          role="group"
          :aria-labelledby="`quick-search-group-${group.key}`"
        >
          <p
            :id="`quick-search-group-${group.key}`"
            class="px-2.5 pt-2 pb-1 text-xs font-medium text-muted-foreground"
          >
            {{ group.title }}
          </p>
          <div
            v-for="entry in group.entries"
            :id="optionId(entry)"
            :key="entry.key"
            role="option"
            :aria-selected="flat[active]?.key === entry.key"
            class="flex min-h-11 cursor-pointer items-start gap-3 rounded-md px-2.5 py-2 md:min-h-10"
            :class="[flat[active]?.key === entry.key && 'bg-accent', entry.destructive && 'text-destructive']"
            @mousemove="active = flat.indexOf(entry)"
            @click="run(entry)"
          >
            <span
              v-if="entry.emoji"
              class="flex size-4 shrink-0 items-center justify-center pt-0.5 text-sm leading-none"
              aria-hidden="true"
              >{{ entry.emoji }}</span
            >
            <AppIcon
              v-else
              :icon="entry.icon"
              size="sm"
              class="mt-0.5 shrink-0"
              :class="!entry.destructive && 'text-muted-foreground'"
            />
            <div class="flex min-w-0 flex-1 flex-col gap-0.5">
              <span class="truncate text-sm font-medium">{{ entry.label }}</span>
              <SnippetText
                v-if="entry.snippet?.length"
                :parts="entry.snippet"
                class="line-clamp-2 text-xs text-muted-foreground"
              />
            </div>
            <span
              v-if="entry.hint"
              class="shrink-0 pt-0.5 text-xs text-muted-foreground"
              >{{ entry.hint }}</span
            >
          </div>
        </div>
        <p
          v-if="error && debounced"
          role="alert"
          class="px-3 py-6 text-center text-sm text-destructive"
        >
          Не удалось выполнить поиск
        </p>
        <p
          v-else-if="debounced && !isFetching && !flat.length"
          class="px-3 py-8 text-center text-sm text-muted-foreground"
        >
          Ничего не нашлось по запросу «{{ debounced }}»
        </p>
      </div>
      <div
        class="hidden items-center gap-4 border-t border-border px-4 py-2 text-xs text-muted-foreground sm:flex"
        aria-hidden="true"
      >
        <span>↑↓ — выбрать</span>
        <span>Enter — открыть</span>
        <span class="flex-1" />
        <span>{{ isMac ? '⌘K' : 'Ctrl K' }} — отовсюду</span>
      </div>
    </div>
  </AppModal>

  <input
    ref="fileInput"
    type="file"
    multiple
    class="hidden"
    :accept="AUDIO_ACCEPT"
    @change="onPicked"
  />
  <UploadModal
    v-model="uploadOpen"
    :files="pendingFiles"
    :default-project-id="currentProjectId"
  />
</template>

<script setup lang="ts">
import { useQuery } from '@pinia/colada'
import { refDebounced, useEventListener } from '@vueuse/core'
import { AudioLines, Folder, Lock, Plus, Search, Settings, Trash2, Upload } from '@lucide/vue'
import type { Component } from 'vue'
import { recordingsList, type SnippetPartSchema } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'
import { settingsNavigation } from '~/navigation/settings'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import { useSidebarProjects } from '~/features/project/composables/useProjects'
import { useProjectCreate } from '~/features/project/composables/useProjectsSidebar'
import type { Recording } from '../../resources/recording'
import { recordingTitle } from '../../composables/useRecordingLabels'
import { useQuickSearch, useRecentRecordings } from '../../composables/useQuickSearch'
import { AUDIO_ACCEPT } from '../../utils/audioUpload'
import SnippetText from '../SnippetText.vue'
import UploadModal from '../upload/UploadModal.vue'

/**
 * ⌘K: one box for recordings (full-text search), projects and commands. Empty: the recordings opened lately (or the
 * newest ones), the open screen's actions and the global ones. Typing: matching recordings, projects and commands.
 */
const { open, pageCommands } = useQuickSearch()
const recents = useRecentRecordings()
const client = useApiClient()
const route = useRoute()
const { formatDate } = useDate()
const { user } = useSession()
const { isAdmin } = useOrganizationRole()
const createProject = useProjectCreate()
const isMac = import.meta.client && /Mac|iPhone|iPad/.test(navigator.platform)

const query = ref('')
const normalized = computed(() => query.value.trim())
const debounced = refDebounced(normalized, 250)
const active = ref(0)
const input = ref<HTMLInputElement>()

const recent = ref<{ id: string; title: string }[]>([])

const { data, asyncStatus, error } = useQuery({
  key: () => ['recordings', 'quick-search', debounced.value],
  query: async ({ signal }) =>
    (
      await recordingsList({
        client,
        throwOnError: true,
        signal,
        query: { search: debounced.value || undefined, page_size: debounced.value ? 6 : 5 },
      })
    ).data.data,
  // Without a query the newest recordings stand in for «Недавние» until the user has opened some.
  enabled: () => open.value && Boolean(debounced.value || !recent.value.length),
  placeholderData: (previous) => previous,
})
const isFetching = computed(() => asyncStatus.value === 'loading')
const { items: projects } = useSidebarProjects()

type Entry = {
  key: string
  label: string
  icon: Component
  emoji?: string
  hint?: string
  snippet?: SnippetPartSchema[] | null
  destructive?: boolean
  keywords?: string
  run: () => void
}
type Group = { key: string; title: string; entries: Entry[] }

// A transcript hit opens at its first matching segment (`?t=`) with the words highlighted (`?q=`).
const openRecording = (id: string, search?: string, startMs?: number | null) =>
  navigateTo({
    name: 'recordings-id',
    params: { id },
    query: search ? { q: search, ...(startMs != null ? { t: String(startMs) } : {}) } : undefined,
  })

const recordingEntry = (recording: Recording): Entry => ({
  key: `recording-${recording.id}`,
  label: recordingTitle(recording),
  icon: recording.visibility === 'personal' ? Lock : AudioLines,
  hint: formatDate(recording.recorded_at, { type: 'date' }) ?? undefined,
  snippet: recording.snippet,
  run: () =>
    void (recording.snippet?.length
      ? openRecording(recording.id, debounced.value, recording.snippet_start_ms)
      : openRecording(recording.id)),
})

const fileInput = ref<HTMLInputElement>()
const uploadOpen = ref(false)
const pendingFiles = shallowRef<File[]>([])
const currentProjectId = computed(() =>
  route.name === 'projects-id' ? String(route.params.id) : ((route.query.project as string | undefined) ?? null),
)
const onPicked = (event: Event) => {
  const target = event.target as HTMLInputElement
  const files = [...(target.files ?? [])]
  target.value = ''
  if (!files.length) return
  pendingFiles.value = files
  uploadOpen.value = true
}

const globalCommands = computed<Entry[]>(() => {
  const superuser = Boolean(user.value?.is_superuser)
  const settings = settingsNavigation
    .filter((item) => (!item.adminOnly || isAdmin.value) && (!item.superuserOnly || superuser))
    .filter((item) => item.section !== 'instance' && item.to.name !== 'settings-organizations')
    .map<Entry>((item) => ({
      key: `settings-${item.to.name}`,
      label: `Настройки: ${item.label}`,
      icon: item.icon,
      keywords: 'настройки параметры',
      run: () => void navigateTo(item.to),
    }))
  return [
    {
      key: 'upload',
      label: 'Загрузить запись',
      icon: Upload,
      keywords: 'файл аудио импорт',
      run: () => fileInput.value?.click(),
    },
    {
      key: 'new-project',
      label: 'Новый проект',
      icon: Plus,
      keywords: 'создать проект',
      run: () => {
        createProject.value = true
      },
    },
    {
      key: 'trash',
      label: 'Корзина',
      icon: Trash2,
      keywords: 'удалённые восстановить',
      run: () => void navigateTo({ name: 'recordings', query: { deleted: '1' } }),
    },
    {
      key: 'settings',
      label: 'Настройки',
      icon: Settings,
      keywords: 'параметры',
      run: () => void navigateTo({ name: 'settings' }),
    },
    ...settings,
  ]
})

const pageEntries = computed<Entry[]>(() =>
  (pageCommands.value?.commands ?? []).map((command) => ({
    key: `page-${command.id}`,
    label: command.label,
    icon: command.icon,
    destructive: command.destructive,
    keywords: command.keywords,
    run: command.run,
  })),
)

const matches = (entry: Entry, text: string) =>
  `${entry.label} ${entry.keywords ?? ''}`.toLocaleLowerCase('ru').includes(text.toLocaleLowerCase('ru'))

const groups = computed<Group[]>(() => {
  const text = normalized.value
  const pageTitle = pageCommands.value?.title ?? 'Эта страница'
  if (!text) {
    const recentEntries: Entry[] = recent.value.length
      ? recent.value.slice(0, 5).map((item) => ({
          key: `recording-${item.id}`,
          label: item.title,
          icon: AudioLines,
          run: () => void openRecording(item.id),
        }))
      : (data.value ?? []).map(recordingEntry)
    return [
      { key: 'recent', title: recent.value.length ? 'Недавние' : 'Последние записи', entries: recentEntries },
      { key: 'page', title: pageTitle, entries: pageEntries.value },
      { key: 'actions', title: 'Действия', entries: globalCommands.value.slice(0, 4) },
    ].filter((group) => group.entries.length)
  }
  const projectEntries = projects.value
    .filter((project) => project.name.toLocaleLowerCase('ru').includes(text.toLocaleLowerCase('ru')))
    .slice(0, 4)
    .map<Entry>((project) => ({
      key: `project-${project.id}`,
      label: project.name,
      emoji: project.emoji ?? undefined,
      icon: project.is_private ? Lock : Folder,
      hint: project.is_private ? 'Приватный' : 'Проект',
      run: () => void navigateTo({ name: 'projects-id', params: { id: project.id } }),
    }))
  // Results of the previous query stay until the new ones arrive (placeholderData), but only for the same text.
  const recordingEntries = debounced.value === text ? (data.value ?? []).map(recordingEntry) : []
  return [
    { key: 'recordings', title: 'Записи', entries: recordingEntries },
    { key: 'projects', title: 'Проекты', entries: projectEntries },
    { key: 'page', title: pageTitle, entries: pageEntries.value.filter((entry) => matches(entry, text)) },
    { key: 'actions', title: 'Действия', entries: globalCommands.value.filter((entry) => matches(entry, text)) },
  ].filter((group) => group.entries.length)
})
const flat = computed(() => groups.value.flatMap((group) => group.entries))
const optionId = (entry: Entry) => `quick-search-${entry.key}`

watch(
  () => flat.value.map((entry) => entry.key).join(),
  () => {
    active.value = 0
  },
)
watch(open, (value) => {
  if (!value) return
  query.value = ''
  recent.value = recents.list()
  void nextTick(() => input.value?.focus())
})

const run = (entry: Entry) => {
  open.value = false
  entry.run()
}

const onKeydown = (event: KeyboardEvent) => {
  const count = flat.value.length
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!count) return
    active.value = (active.value + (event.key === 'ArrowDown' ? 1 : count - 1)) % count
    void nextTick(() =>
      document.getElementById(optionId(flat.value[active.value]!))?.scrollIntoView({ block: 'nearest' }),
    )
  } else if (event.key === 'Enter' && flat.value[active.value]) {
    event.preventDefault()
    run(flat.value[active.value]!)
  }
}

// ⌘K / Ctrl+K anywhere in the workspace.
useEventListener('keydown', (event: KeyboardEvent) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    open.value = !open.value
  }
})
</script>
