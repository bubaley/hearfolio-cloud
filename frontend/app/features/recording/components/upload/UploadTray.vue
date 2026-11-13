<template>
  <div
    v-if="uploads.items.length"
    class="fixed inset-x-2 bottom-2 z-40 md:inset-x-auto md:right-4 md:bottom-4 md:w-96"
    role="region"
    aria-label="Загрузки"
  >
    <div
      class="overflow-hidden rounded-xl border border-border-strong bg-popover text-popover-foreground shadow-overlay"
    >
      <div class="flex min-h-11 items-center gap-2 pr-1 pl-3">
        <AppIcon
          :icon="summary.icon"
          :loading="summary.busy"
          size="sm"
          :tone="summary.tone"
          class="shrink-0"
        />
        <button
          type="button"
          class="flex min-h-11 min-w-0 flex-1 flex-col justify-center text-left outline-none focus-visible:underline"
          :aria-expanded="expanded"
          @click="expanded = !expanded"
        >
          <span class="truncate text-sm font-medium">{{ summary.title }}</span>
          <span
            v-if="summary.hint"
            class="truncate text-xs text-muted-foreground"
            >{{ summary.hint }}</span
          >
        </button>
        <AppButton
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="size-11 md:size-control-md"
          :icon="expanded ? ChevronDown : ChevronUp"
          :aria-label="expanded ? 'Свернуть' : 'Развернуть'"
          @click="expanded = !expanded"
        />
        <AppButton
          v-if="!uploads.active.length"
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="size-11 md:size-control-md"
          :icon="X"
          aria-label="Закрыть"
          @click="closeAll"
        />
      </div>
      <AppProgress
        v-if="uploads.active.length"
        :value="totalPercent"
        class="h-0.5 rounded-none"
        aria-label="Общий прогресс загрузки"
      />
      <ul
        v-if="expanded"
        class="max-h-72 overflow-y-auto border-t border-border"
      >
        <li
          v-for="item in uploads.items"
          :key="item.key"
          class="flex min-h-14 items-center gap-2 border-b border-border py-2 pr-1 pl-3 last:border-b-0"
        >
          <div class="flex min-w-0 flex-1 flex-col gap-1">
            <component
              :is="item.state === 'done' && item.recordingId ? NuxtLink : 'span'"
              v-bind="
                item.state === 'done' && item.recordingId
                  ? { to: { name: 'recordings-id', params: { id: item.recordingId } } }
                  : {}
              "
              class="truncate text-sm"
              :class="item.state === 'done' && 'underline-offset-2 hover:underline'"
              >{{ item.name }}</component
            >
            <AppProgress
              v-if="item.state === 'uploading' || item.state === 'preparing' || item.state === 'completing'"
              :value="percent(item)"
              class="h-1"
              :aria-label="`Загрузка ${item.name}`"
            />
            <span
              class="text-xs"
              :class="item.state === 'failed' ? 'line-clamp-3 text-destructive' : 'truncate text-muted-foreground'"
              >{{ stateText(item) }}</span
            >
          </div>
          <AppButton
            v-if="item.state === 'failed'"
            variant="ghost"
            size="icon"
            text-variant="muted"
            class="size-11 md:size-control-md"
            :icon="RotateCcw"
            :aria-label="`Повторить загрузку ${item.name}`"
            title="Повторить"
            @click="uploads.retry(item.key)"
          />
          <AppButton
            v-if="item.state !== 'done'"
            variant="ghost"
            size="icon"
            text-variant="muted"
            class="size-11 md:size-control-md"
            :icon="X"
            :aria-label="`Отменить загрузку ${item.name}`"
            title="Отменить"
            @click="uploads.cancel(item.key)"
          />
          <AppIcon
            v-else
            :icon="CircleCheck"
            tone="success"
            size="sm"
            class="mx-3.5 shrink-0"
            label="Загружено"
          />
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ChevronDown, ChevronUp, CircleAlert, CircleCheck, CloudUpload, RotateCcw, X } from '@lucide/vue'
import { NuxtLink } from '#components'
import { useUploadStore, type UploadItem } from '../../stores/useUploadStore'
import { useAiOptions } from '../../composables/useRecordingDetail'
import { uploadDoneHint } from '../../utils/processingCopy'

const uploads = useUploadStore()
const expanded = ref(true)
// Only once there is something in the tray (the layout also renders before an organization is chosen).
const { data: aiOptions } = useAiOptions(() => uploads.items.length > 0)

const percent = (item: UploadItem) => (item.size ? Math.min(100, Math.round((item.loaded / item.size) * 100)) : 0)

const totalPercent = computed(() => {
  const active = uploads.active
  const size = active.reduce((sum, item) => sum + item.size, 0)
  return size ? Math.round((active.reduce((sum, item) => sum + item.loaded, 0) / size) * 100) : 0
})

const summary = computed(() => {
  const failed = uploads.items.filter((item) => item.state === 'failed').length
  const active = uploads.active.length
  if (active)
    return {
      icon: CloudUpload,
      busy: true,
      tone: 'muted' as const,
      title: active === 1 ? 'Загружается 1 файл' : `Загружается файлов: ${active}`,
      hint: `${totalPercent.value}%${failed ? ` · ошибок: ${failed}` : ''}`,
    }
  if (failed)
    return {
      icon: CircleAlert,
      busy: false,
      tone: 'destructive' as const,
      title: failed === 1 ? 'Файл не загрузился' : `Не загрузилось файлов: ${failed}`,
      hint: 'Повторите или отмените загрузку',
    }
  return {
    icon: CircleCheck,
    busy: false,
    tone: 'success' as const,
    title: 'Загрузка завершена',
    hint: uploadDoneHint(aiOptions.value),
  }
})

const stateText = (item: UploadItem) => {
  switch (item.state) {
    case 'queued':
      return 'В очереди'
    case 'preparing':
      return 'Подготовка…'
    case 'uploading':
      return `${percent(item)}%`
    case 'completing':
      return 'Завершаем…'
    case 'done':
      return 'Загружено — откройте запись'
    case 'failed':
      return item.error ?? 'Не удалось загрузить'
  }
}

const closeAll = () => {
  // A failed upload left a recording waiting for its audio: closing gives up on it like «Отменить».
  // `cancel` and `dismiss` replace the array, so this loop walks the snapshot taken here.
  const snapshot = uploads.items
  for (const item of snapshot) {
    if (item.state === 'failed') void uploads.cancel(item.key)
    else uploads.dismiss(item.key)
  }
}
</script>
