<template>
  <dl class="flex flex-col text-sm">
    <div
      v-for="row in rows"
      :key="row.key"
      class="grid min-h-9 grid-cols-[8.75rem_1fr] items-start gap-2 max-md:min-h-11 md:grid-cols-[9rem_1fr]"
    >
      <dt class="flex min-h-9 items-center gap-2 px-1 text-muted-foreground max-md:min-h-11">
        <AppIcon
          :icon="row.icon"
          size="sm"
          class="shrink-0"
        />
        <span class="truncate">{{ row.label }}</span>
      </dt>
      <dd class="min-w-0">
        <ProjectPicker
          v-if="row.key === 'project'"
          :project="recording.project"
          @change="(project) => emit('project', project)"
        />
        <TagPicker
          v-else-if="row.key === 'tags'"
          :tags="recording.tags"
          @change="(tags) => emit('tags', tags)"
        />
        <div
          v-else-if="row.key === 'visibility'"
          class="flex min-h-9 items-center px-1 max-md:min-h-11"
        >
          <div
            v-if="isAuthor"
            role="radiogroup"
            aria-label="Доступ"
            class="inline-flex rounded-md bg-muted p-0.5"
          >
            <button
              v-for="option in VISIBILITY_OPTIONS"
              :key="option.value"
              type="button"
              role="radio"
              :aria-checked="recording.visibility === option.value"
              class="flex h-7 items-center gap-1.5 rounded px-2.5 text-xs transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring max-md:h-10 max-md:px-3"
              :class="
                recording.visibility === option.value
                  ? 'bg-background font-medium text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              "
              @click="recording.visibility !== option.value && emit('visibility', option.value)"
            >
              <AppIcon
                :icon="option.icon"
                size="xs"
              />
              {{ option.label }}
            </button>
          </div>
          <span
            v-else
            class="inline-flex items-center gap-1.5"
          >
            <AppIcon
              :icon="recording.visibility === 'personal' ? Lock : Users"
              size="sm"
              class="text-muted-foreground"
            />
            {{ recording.visibility === 'personal' ? 'Личная' : 'Общая' }}
          </span>
          <!-- A shared recording in a private project is not for the whole organization: say who sees it. -->
          <span
            v-if="privateProject"
            class="ml-2 inline-flex min-w-0 items-center gap-1 text-muted-foreground"
            :title="`Видят только участники проекта «${privateProject.name}»`"
          >
            <span v-if="!isAuthor">·</span>
            <AppIcon
              :icon="Lock"
              size="xs"
              class="shrink-0"
              label="Приватный проект"
            />
            <span class="truncate">в проекте {{ privateProject.name }}</span>
          </span>
        </div>
        <div
          v-else-if="row.key === 'author'"
          class="flex min-h-9 min-w-0 items-center gap-2 px-1 max-md:min-h-11"
        >
          <AppAvatar
            variant="soft"
            size="xsmall"
            :name="author"
          />
          <span class="truncate">{{ author }}</span>
        </div>
        <div
          v-else
          class="flex min-h-9 min-w-0 items-center px-1 py-1.5 max-md:min-h-11"
          :class="!row.value && 'text-muted-foreground'"
        >
          <span class="min-w-0 break-words">{{ row.value || '—' }}</span>
        </div>
      </dd>
    </div>
  </dl>
</template>

<script setup lang="ts">
import { CalendarDays, Folder, Lock, ShieldCheck, Tags, Timer, UserRound, Users } from '@lucide/vue'
import type { Component } from 'vue'
import type { RecordingSource, RecordingVisibility } from '~/shared/api/generated'
import type { RecordingDetail, TagBrief } from '../../resources/recording'
import type { ProjectBrief } from '~/features/project/resources/project'
import ProjectPicker from './ProjectPicker.vue'
import TagPicker from './TagPicker.vue'

const props = defineProps<{ recording: RecordingDetail; isAuthor: boolean }>()
const emit = defineEmits<{
  project: [project: ProjectBrief | null]
  tags: [tags: TagBrief[]]
  visibility: [value: RecordingVisibility]
}>()

// Every property is shown at once: nothing folds under a toggle.
const { formatDate } = useDate()

const SOURCES: Record<RecordingSource, string> = {
  desktop: 'приложение на компьютере',
  android: 'Android',
  web: 'загрузка из браузера',
  import: 'импорт',
}
const VISIBILITY_OPTIONS = [
  { value: 'organization' as const, label: 'Общая', icon: Users },
  { value: 'personal' as const, label: 'Личная', icon: Lock },
]

const author = computed(() => userDisplayName(props.recording.created_by) || 'Удалённый пользователь')

const privateProject = computed(() =>
  props.recording.visibility === 'organization' && props.recording.project?.is_private ? props.recording.project : null,
)

type Row = { key: string; label: string; icon: Component; value?: string }
const rows = computed<Row[]>(() => {
  const recording = props.recording
  const created = formatDate(recording.recorded_at, { format: 'D MMMM YYYY, HH:mm' })
  return [
    { key: 'project', label: 'Проект', icon: Folder },
    { key: 'tags', label: 'Теги', icon: Tags },
    { key: 'visibility', label: 'Доступ', icon: ShieldCheck },
    { key: 'author', label: 'Автор', icon: UserRound },
    {
      key: 'created',
      label: 'Создано',
      icon: CalendarDays,
      value: created ? `${created} · ${SOURCES[recording.source] ?? recording.source}` : '',
    },
    {
      key: 'duration',
      label: 'Длительность',
      icon: Timer,
      value: recording.duration_ms ? formatDuration(recording.duration_ms) : '',
    },
  ]
})
</script>
