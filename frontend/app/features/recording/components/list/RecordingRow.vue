<template>
  <NuxtLink
    :to="{ name: 'recordings-id', params: { id: recording.id } }"
    class="group flex min-h-12 items-start gap-3 rounded-md px-2 py-2.5 transition-colors outline-none hover:bg-row-hover focus-visible:ring-2 focus-visible:ring-ring @3xl:min-h-11 @3xl:items-center @3xl:py-1.5"
  >
    <AppIcon
      :icon="recording.visibility === 'personal' ? Lock : AudioLines"
      size="sm"
      class="mt-0.5 shrink-0 text-muted-foreground @3xl:mt-0"
      :label="recording.visibility === 'personal' ? 'Личная запись' : undefined"
    />
    <div class="flex min-w-0 flex-1 flex-col gap-1 @3xl:gap-0.5">
      <div class="flex min-w-0 items-center gap-3">
        <span
          class="line-clamp-2 min-w-0 text-sm font-medium break-words @3xl:line-clamp-1"
          :class="!recording.title.trim() && 'text-muted-foreground'"
          >{{ title }}</span
        >
        <!-- A wrapper: the label's own `inline-flex` would beat `hidden` on the component root. -->
        <span class="hidden min-w-0 @3xl:inline-flex">
          <RecordingStatusLabel :recording="recording" />
        </span>
      </div>
      <SnippetText
        v-if="recording.snippet?.length"
        :parts="recording.snippet"
        class="line-clamp-2 text-xs text-muted-foreground"
      />
      <!-- Narrow lists (phones, a tablet with the sidebar open): one muted meta line under the title. -->
      <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground @3xl:hidden">
        <RecordingStatusLabel :recording="recording" />
        <span>{{ time }}</span>
        <span v-if="recording.duration_ms">{{ formatClock(recording.duration_ms) }}</span>
        <span
          v-if="recording.project && !hideProject"
          class="inline-flex min-w-0 items-center gap-1"
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
        <TagChip
          v-for="tag in recording.tags.slice(0, 3)"
          :key="tag.id"
          :name="tag.name"
          :color="tag.color"
          class="max-w-40 shrink-0"
        />
      </div>
    </div>
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
      <span class="w-12 text-right tabular-nums">{{
        recording.duration_ms ? formatClock(recording.duration_ms) : ''
      }}</span>
      <AppAvatar
        variant="soft"
        size="xsmall"
        :name="author"
        :title="author"
      />
      <span class="w-10 text-right tabular-nums">{{ time }}</span>
    </div>
  </NuxtLink>
</template>

<script setup lang="ts">
import { AudioLines, Folder, Lock } from '@lucide/vue'
import type { Recording } from '../../resources/recording'
import { recordingTitle } from '../../composables/useRecordingLabels'
import RecordingStatusLabel from '../RecordingStatusLabel.vue'
import SnippetText from '../SnippetText.vue'
import TagChip from '~/features/tag/components/TagChip.vue'

const props = defineProps<{ recording: Recording; time: string; hideProject?: boolean }>()

const title = computed(() => recordingTitle(props.recording))
const author = computed(() => userDisplayName(props.recording.created_by) || 'Удалённый пользователь')
</script>
