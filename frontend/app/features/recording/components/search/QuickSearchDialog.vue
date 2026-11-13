<template>
  <AppModal
    v-model="open"
    title="Поиск записей"
    hide-title
    width="36rem"
    content-class="top-[12vh] translate-y-0 gap-0 overflow-hidden p-0 sm:top-[15vh]"
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
          placeholder="Найти запись по названию или тексту…"
          aria-label="Поиск записей"
          aria-controls="quick-search-results"
          :aria-activedescendant="results[active] ? `quick-search-${results[active]!.id}` : undefined"
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

      <div class="max-h-[min(26rem,60dvh)] overflow-y-auto p-1.5">
        <p
          v-if="!debounced"
          class="px-2.5 pt-1.5 pb-1 text-xs font-medium text-muted-foreground"
        >
          Недавние
        </p>
        <ul
          id="quick-search-results"
          role="listbox"
          aria-label="Найденные записи"
        >
          <li
            v-for="(recording, index) in results"
            :id="`quick-search-${recording.id}`"
            :key="recording.id"
            role="option"
            :aria-selected="index === active"
            class="flex min-h-11 cursor-pointer items-start gap-3 rounded-md px-2.5 py-2"
            :class="index === active && 'bg-accent'"
            @mousemove="active = index"
            @click="go(recording)"
          >
            <AppIcon
              :icon="recording.visibility === 'personal' ? Lock : AudioLines"
              size="sm"
              class="mt-0.5 shrink-0 text-muted-foreground"
            />
            <div class="flex min-w-0 flex-1 flex-col gap-0.5">
              <span class="truncate text-sm font-medium">{{ recordingTitle(recording) }}</span>
              <SnippetText
                v-if="recording.snippet?.length"
                :parts="recording.snippet"
                class="line-clamp-2 text-xs text-muted-foreground"
              />
            </div>
            <span class="shrink-0 pt-0.5 text-xs text-muted-foreground">{{
              formatDate(recording.recorded_at, { type: 'date' })
            }}</span>
          </li>
        </ul>
        <p
          v-if="error"
          role="alert"
          class="px-3 py-6 text-center text-sm text-destructive"
        >
          Не удалось выполнить поиск
        </p>
        <p
          v-else-if="debounced && !isFetching && !results.length"
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
        <span>⌘K — поиск отовсюду</span>
      </div>
    </div>
  </AppModal>
</template>

<script setup lang="ts">
import { useQuery } from '@pinia/colada'
import { refDebounced, useEventListener } from '@vueuse/core'
import { AudioLines, Lock, Search } from '@lucide/vue'
import { recordingsList } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'
import type { Recording } from '../../resources/recording'
import { recordingTitle } from '../../composables/useRecordingLabels'
import { useQuickSearch } from '../../composables/useQuickSearch'
import SnippetText from '../SnippetText.vue'

const { open } = useQuickSearch()
const client = useApiClient()
const { formatDate } = useDate()

const query = ref('')
const debounced = refDebounced(
  computed(() => query.value.trim()),
  250,
)
const active = ref(0)
const input = ref<HTMLInputElement>()

const { data, asyncStatus, error } = useQuery({
  key: () => ['recordings', 'quick-search', debounced.value],
  query: async ({ signal }) =>
    (
      await recordingsList({
        client,
        throwOnError: true,
        signal,
        query: { search: debounced.value || undefined, page_size: 8 },
      })
    ).data.data,
  enabled: () => open.value,
  placeholderData: (previous) => previous,
})
const results = computed<Recording[]>(() => data.value ?? [])
const isFetching = computed(() => asyncStatus.value === 'loading')

watch(results, () => {
  active.value = 0
})
watch(open, (value) => {
  if (value) {
    query.value = ''
    void nextTick(() => input.value?.focus())
  }
})

const go = (recording: Recording) => {
  open.value = false
  void navigateTo({ name: 'recordings-id', params: { id: recording.id } })
}

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const count = results.value.length
    if (!count) return
    active.value = (active.value + (event.key === 'ArrowDown' ? 1 : count - 1)) % count
    void nextTick(() =>
      document.getElementById(`quick-search-${results.value[active.value]?.id}`)?.scrollIntoView({ block: 'nearest' }),
    )
  } else if (event.key === 'Enter' && results.value[active.value]) {
    event.preventDefault()
    go(results.value[active.value]!)
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
