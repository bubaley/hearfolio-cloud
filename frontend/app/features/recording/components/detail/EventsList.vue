<template>
  <div class="flex flex-col gap-4">
    <dl
      v-if="model"
      class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm"
    >
      <dt class="flex items-center gap-1.5 text-muted-foreground">
        <AppIcon
          :icon="Cpu"
          size="sm"
        />
        Модель расшифровки
      </dt>
      <dd class="min-w-0 break-all">{{ model }}</dd>
    </dl>
    <AppAlert
      v-if="error && !events.length"
      tone="destructive"
      title="Не удалось загрузить историю"
    >
      <AppTextButton
        label="Повторить"
        weight="medium"
        @click="refetch()"
      />
    </AppAlert>
    <div
      v-else-if="isLoading && !events.length"
      class="flex flex-col gap-4"
    >
      <AppSkeleton
        v-for="row in 4"
        :key="row"
        :lines="1"
        class="w-2/3"
      />
    </div>
    <p
      v-else-if="!events.length"
      class="py-6 text-center text-sm text-muted-foreground"
    >
      История пока пуста
    </p>
    <ol
      v-else
      class="relative flex flex-col"
      aria-label="История записи"
    >
      <li
        v-for="event in events"
        :key="event.id"
        class="relative flex gap-3 pb-4 last:pb-0"
      >
        <span
          class="relative z-1 flex size-7 shrink-0 items-center justify-center rounded-full border border-border bg-background"
          :class="event.kind === 'failed' ? 'text-destructive' : 'text-muted-foreground'"
        >
          <AppIcon
            :icon="getEventLabel(event.kind).icon"
            size="xs"
          />
        </span>
        <div class="flex min-w-0 flex-1 flex-col gap-0.5 pt-1">
          <p class="text-sm">
            <span class="font-medium">{{ actorName(event) }}</span>
            <span class="text-muted-foreground"> · {{ getEventLabel(event.kind).label.toLowerCase() }}</span>
          </p>
          <p
            v-if="detail(event)"
            class="text-sm break-words text-muted-foreground"
          >
            {{ detail(event) }}
          </p>
          <time
            :datetime="event.created_at"
            class="text-xs text-muted-foreground"
            >{{ formatDate(event.created_at) }}</time
          >
        </div>
      </li>
    </ol>
  </div>
</template>

<script setup lang="ts">
import { Cpu } from '@lucide/vue'
import type { RecordingEvent, useRecordingEvents } from '../../composables/useRecordingDetail'
import { getEventLabel } from '../../composables/useRecordingLabels'

const props = defineProps<{ state: ReturnType<typeof useRecordingEvents>; model?: string | null }>()
const { data, isLoading, error, refetch } = props.state
const events = computed<RecordingEvent[]>(() => data.value ?? [])
const { formatDate } = useDate()

const actorName = (event: RecordingEvent) => (event.actor ? userDisplayName(event.actor) : 'Hearfolio AI')

const text = (value: unknown) => (typeof value === 'string' ? value : '')
const names = (value: unknown) => (Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [])

const detail = (event: RecordingEvent) => {
  const data = event.data ?? {}
  switch (event.kind) {
    case 'renamed':
      return text(data.to) ? `«${text(data.to)}»` : ''
    case 'tagged': {
      const added = names(data.added)
      const removed = names(data.removed)
      return [added.length ? `+ ${added.join(', ')}` : '', removed.length ? `− ${removed.join(', ')}` : '']
        .filter(Boolean)
        .join('  ')
    }
    case 'failed':
      return text(data.message)
    case 'transcribed':
      return text(data.model)
    case 'result_created':
      return text(data.title) ? `«${text(data.title)}»` : ''
    case 'moved':
      return data.to_project_id ? '' : 'Убрана из проекта'
    default:
      return ''
  }
}
</script>
