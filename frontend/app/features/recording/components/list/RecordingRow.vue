<template>
  <!-- A stretched link (the title's ::after covers the row) keeps the checkbox and buttons outside the <a>. -->
  <div
    class="group relative flex min-h-12 items-start gap-3 rounded-md px-2 py-2.5 transition-colors has-[[data-row-link]:focus-visible]:ring-2 has-[[data-row-link]:focus-visible]:ring-ring @3xl:min-h-11 @3xl:items-center @3xl:py-1.5"
    :class="selected ? 'bg-accent/70' : 'hover:bg-row-hover'"
    :draggable="selectable"
    data-recording-row
    @dragstart="onDragStart"
  >
    <span
      v-if="selectable"
      class="relative z-1 mt-0.5 flex size-4 shrink-0 items-center justify-center @3xl:mt-0"
      @click.capture="rememberShift"
    >
      <AppCheckbox
        :model-value="selected"
        :aria-label="`Выбрать «${title}»`"
        class="absolute inset-0 justify-center transition-opacity max-md:-inset-3"
        :class="selecting || selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-within:opacity-100'"
        @update:model-value="emit('select', shift)"
      />
      <AppIcon
        :icon="icon"
        size="sm"
        class="text-muted-foreground transition-opacity"
        :class="selecting || selected ? 'opacity-0' : 'group-hover:opacity-0'"
        :label="recording.visibility === 'personal' ? 'Личная запись' : undefined"
      />
    </span>
    <AppIcon
      v-else
      :icon="icon"
      size="sm"
      class="mt-0.5 shrink-0 text-muted-foreground @3xl:mt-0"
      :label="recording.visibility === 'personal' ? 'Личная запись' : undefined"
    />
    <div class="flex min-w-0 flex-1 flex-col gap-1 @3xl:gap-0.5">
      <div class="flex min-w-0 items-center gap-3">
        <NuxtLink
          v-if="!trash"
          :to="link"
          draggable="false"
          data-row-link
          class="line-clamp-2 min-w-0 text-sm font-medium break-words outline-none after:absolute after:inset-0 after:rounded-md @3xl:line-clamp-1"
          :class="!recording.title.trim() && 'text-muted-foreground'"
          >{{ title }}</NuxtLink
        >
        <span
          v-else
          class="line-clamp-2 min-w-0 text-sm font-medium break-words @3xl:line-clamp-1"
          :class="!recording.title.trim() && 'text-muted-foreground'"
          >{{ title }}</span
        >
        <!-- A wrapper: the label's own `inline-flex` would beat `hidden` on the component root. -->
        <span
          v-if="!trash"
          class="hidden min-w-0 @3xl:inline-flex"
        >
          <RecordingStatusLabel :recording="recording" />
        </span>
      </div>
      <SnippetText
        v-if="recording.snippet?.length"
        :parts="recording.snippet"
        class="line-clamp-2 text-xs text-muted-foreground"
      />
      <!-- Trash: when it was deleted and how long it can still come back. -->
      <p
        v-if="trash"
        class="text-xs text-muted-foreground"
      >
        {{ trashHint }}<template v-if="!canManage"> · восстановить может автор или администратор</template>
      </p>
      <!-- Narrow lists (phones, a tablet with the sidebar open): one muted meta line under the title. -->
      <div
        v-else
        class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground @3xl:hidden"
      >
        <RecordingStatusLabel :recording="recording" />
        <span class="tabular-nums">{{ meta }}</span>
        <!-- The separator travels with the project, so a wrapped line never ends with «·». -->
        <template v-if="recording.project && !hideProject">
          <span class="inline-flex min-w-0 items-center gap-1">
            <span
              aria-hidden="true"
              class="mr-0.5"
              >·</span
            >
            <span
              v-if="recording.project.emoji"
              class="leading-none"
              aria-hidden="true"
              >{{ recording.project.emoji }}</span
            >
            <AppIcon
              v-else
              :icon="Folder"
              size="xs"
            />
            <span class="max-w-36 truncate">{{ recording.project.name }}</span>
          </span>
        </template>
        <TagChip
          v-for="tag in recording.tags.slice(0, 3)"
          :key="tag.id"
          :name="tag.name"
          :color="tag.color"
          class="ml-0.5 max-w-40 shrink-0"
        />
      </div>
    </div>

    <AppButton
      v-if="trash && canManage"
      size="sm"
      variant="outline"
      :icon="RotateCcw"
      label="Восстановить"
      class="relative z-1 shrink-0 self-center max-md:h-11"
      @click="emit('restore')"
    />
    <AppButton
      v-else-if="stalled && canManage"
      size="sm"
      variant="ghost"
      text-variant="muted"
      :icon="Trash2"
      label="Удалить"
      class="relative z-1 shrink-0 self-center max-md:h-11"
      @click="emit('remove')"
    />
    <template v-if="!trash">
      <AppAvatar
        variant="soft"
        size="small"
        class="shrink-0 @3xl:hidden"
        :name="author"
        :title="author"
      />
      <!-- Wide lists: properties in fixed columns to the right, like a Notion database list. The breakpoints are
           container queries on the list (`@container` in RecordingList), so the sidebar and the project page width count. -->
      <div class="hidden shrink-0 items-center gap-3 text-xs text-muted-foreground @3xl:flex">
        <div class="flex w-28 items-center justify-end gap-1 overflow-hidden @5xl:w-44">
          <TagChip
            v-for="tag in recording.tags.slice(0, 2)"
            :key="tag.id"
            :name="tag.name"
            :color="tag.color"
            class="max-w-28 shrink-0"
          />
          <span
            v-if="recording.tags.length > 2"
            class="shrink-0"
            >+{{ recording.tags.length - 2 }}</span
          >
        </div>
        <span
          v-if="!hideProject"
          class="hidden w-36 min-w-0 items-center gap-1 @5xl:inline-flex"
        >
          <template v-if="recording.project">
            <span
              v-if="recording.project.emoji"
              class="shrink-0 leading-none"
              aria-hidden="true"
              >{{ recording.project.emoji }}</span
            >
            <AppIcon
              v-else
              :icon="Folder"
              size="xs"
              class="shrink-0"
            />
            <span class="truncate">{{ recording.project.name }}</span>
          </template>
        </span>
        <span
          class="w-16 text-right tabular-nums"
          :title="recording.duration_ms ? `Длительность ${formatDuration(recording.duration_ms)}` : undefined"
          >{{ recording.duration_ms ? formatDuration(recording.duration_ms) : '' }}</span
        >
        <AppAvatar
          variant="soft"
          size="xsmall"
          :name="author"
          :title="author"
        />
        <span class="w-10 text-right tabular-nums">{{ time }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { AudioLines, Folder, Lock, RotateCcw, Trash2 } from '@lucide/vue'
import { pluralize } from '~/features/project/composables/projectLabels'
import type { Recording } from '../../resources/recording'
import { recordingTitle } from '../../composables/useRecordingLabels'
import RecordingStatusLabel from '../RecordingStatusLabel.vue'
import SnippetText from '../SnippetText.vue'
import TagChip from '~/features/tag/components/TagChip.vue'

const props = defineProps<{
  recording: Recording
  time: string
  hideProject?: boolean
  /** Search query: the row opens the recording at the matching segment. */
  query?: string
  /** Bulk selection: the checkbox replaces the icon on hover (always while something is selected). */
  selectable?: boolean
  selected?: boolean
  selecting?: boolean
  /** «Корзина»: no link, «Восстановить» and the days left. */
  trash?: boolean
  /** Days a deleted recording stays in «Корзина» (the server's retention). */
  trashDays?: number
  /** Restore in the trash, delete of a stalled upload: author or org admin. */
  canManage?: boolean
}>()
const emit = defineEmits<{ select: [range: boolean]; restore: []; remove: []; dragstart: [event: DragEvent] }>()

const { formatDate } = useDate()
const title = computed(() => recordingTitle(props.recording))
const author = computed(() => userDisplayName(props.recording.created_by) || 'Удалённый пользователь')
const icon = computed(() => (props.recording.visibility === 'personal' ? Lock : AudioLines))
const link = computed(() => ({
  name: 'recordings-id',
  params: { id: props.recording.id },
  // A transcript hit opens at its first matching segment (`?t=`) with the words highlighted (`?q=`).
  query:
    props.query && props.recording.snippet?.length
      ? {
          q: props.query,
          ...(props.recording.snippet_start_ms != null ? { t: String(props.recording.snippet_start_ms) } : {}),
        }
      : undefined,
}))
const meta = computed(() =>
  [props.time, props.recording.duration_ms ? formatDuration(props.recording.duration_ms) : '']
    .filter(Boolean)
    .join(' · '),
)
const stalled = computed(() => props.recording.stalled)
let shift = false
const rememberShift = (event: MouseEvent) => {
  shift = event.shiftKey
}

const trashHint = computed(() => {
  const deletedAt = props.recording.deleted_at
  if (!deletedAt) return ''
  const left = Math.ceil((Date.parse(deletedAt) + (props.trashDays ?? 30) * 86_400_000 - Date.now()) / 86_400_000)
  const when = formatDate(deletedAt, { format: 'D MMMM, HH:mm' })
  const remains = left > 0 ? `удалится навсегда через ${pluralize(left, ['день', 'дня', 'дней'])}` : 'удалится сегодня'
  return `Удалена ${when} · ${remains}`
})

const onDragStart = (event: DragEvent) => emit('dragstart', event)
</script>
