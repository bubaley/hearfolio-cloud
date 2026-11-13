<template>
  <span
    v-if="view"
    class="inline-flex min-w-0 shrink-0 items-center gap-1.5 text-xs"
    :class="toneVariants({ tone: view.tone })"
  >
    <AppIcon
      :icon="view.icon"
      :loading="view.active"
      size="xs"
    />
    <span class="truncate">{{ view.label }}</span>
    <AppProgress
      v-if="view.progress !== null"
      :value="view.progress"
      tone="info"
      :aria-label="view.label"
      class="h-1 w-10 shrink-0"
    />
  </span>
</template>

<script setup lang="ts">
import { toneVariants } from '~/shared/ui/app/tone'
import type { Recording } from '../resources/recording'
import { getRecordingStatusView } from '../composables/useRecordingLabels'

const props = defineProps<{
  recording: Pick<Recording, 'status' | 'upload_state' | 'segments_done' | 'segments_total' | 'progress'> &
    Partial<Pick<Recording, 'updated_at'>>
}>()

const view = computed(() => getRecordingStatusView(props.recording))
</script>
