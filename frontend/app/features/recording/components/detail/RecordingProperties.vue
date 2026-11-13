<template>
  <dl class="flex flex-col text-sm">
    <div
      v-for="row in rows"
      :key="row.key"
      class="min-h-9 grid-cols-[6.5rem_1fr] items-start gap-2 max-md:min-h-11 md:grid-cols-[9rem_1fr]"
      :class="expanded || row.level === 'primary' ? 'grid' : row.level === 'wide' ? 'hidden md:grid' : 'hidden'"
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
          class="flex min-h-9 min-w-0 items-center px-1 max-md:min-h-11"
          :class="!row.value && 'text-muted-foreground'"
        >
          <span class="truncate">{{ row.value || '—' }}</span>
        </div>
      </dd>
    </div>
    <button
      type="button"
      class="flex min-h-11 w-fit items-center gap-2 rounded-md px-1 text-left text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <AppIcon
        :icon="expanded ? ChevronUp : ChevronDown"
        size="sm"
      />
      <span class="md:hidden">{{ expanded ? 'Свернуть свойства' : 'Все свойства' }}</span>
      <span class="max-md:hidden">{{ expanded ? 'Свернуть' : 'Ещё' }}</span>
    </button>
  </dl>
</template>

<script setup lang="ts">
import {
  CalendarDays,
  ChevronDown,
  ChevronUp,
  Folder,
  Lock,
  ShieldCheck,
  Tags,
  Timer,
  UserRound,
  Users,
} from '@lucide/vue'
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

// Phones show the editable properties, wider screens add the author; the rest folds under «Ещё» / «Все свойства».
const expanded = ref(false)
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

type Row = { key: string; label: string; icon: Component; value?: string; level: 'primary' | 'wide' | 'more' }
const rows = computed<Row[]>(() => {
  const recording = props.recording
  const created = formatDate(recording.recorded_at, { format: 'D MMMM YYYY, HH:mm' })
  return [
    { key: 'project', label: 'Проект', icon: Folder, level: 'primary' },
    { key: 'tags', label: 'Теги', icon: Tags, level: 'primary' },
    { key: 'visibility', label: 'Доступ', icon: ShieldCheck, level: 'primary' },
    { key: 'author', label: 'Автор', icon: UserRound, level: 'wide' },
    {
      key: 'created',
      label: 'Создано',
      icon: CalendarDays,
      value: created ? `${created} · ${SOURCES[recording.source] ?? recording.source}` : '',
      level: 'more',
    },
    {
      key: 'duration',
      label: 'Длительность',
      icon: Timer,
      value: recording.duration_ms ? formatDuration(recording.duration_ms) : '',
      level: 'more',
    },
  ]
})
</script>
