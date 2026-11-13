<template>
  <AppModal
    v-model="open"
    :title="audio.length === 1 ? 'Загрузить запись' : `Загрузить записи: ${audio.length}`"
    description="Расшифровка и саммари появятся автоматически, когда файл загрузится"
    width="30rem"
  >
    <div class="flex flex-col gap-5">
      <ul
        v-if="audio.length"
        class="flex max-h-48 flex-col overflow-y-auto rounded-md border border-border"
      >
        <li
          v-for="(file, index) in audio"
          :key="index"
          class="flex min-h-10 items-center gap-2.5 border-b border-border px-3 py-2 text-sm last:border-b-0"
        >
          <AppIcon
            :icon="FileAudio"
            size="sm"
            class="shrink-0 text-muted-foreground"
          />
          <span class="min-w-0 flex-1 truncate">{{ file.name }}</span>
          <span class="shrink-0 text-xs text-muted-foreground tabular-nums">{{ formatBytes(file.size) }}</span>
        </li>
      </ul>
      <AppAlert
        v-if="skipped.length"
        tone="warning"
        :title="
          skipped.length === 1
            ? 'Этот файл не аудио и не видео — он будет пропущен'
            : 'Эти файлы не аудио и не видео — они будут пропущены'
        "
        :description="skipped.map((file) => file.name).join(', ')"
      />
      <AppAlert
        v-if="tooLarge.length"
        tone="warning"
        title="Слишком большие файлы (больше 10 ГБ) будут пропущены"
        :description="tooLarge.map((file) => file.name).join(', ')"
      />

      <AppSelect
        v-model="projectId"
        :auto-load="Boolean(projectId)"
        label="Проект"
        placeholder="Без проекта"
        :resource="projectResource"
        search-param="name"
        :query="{ archived: false }"
        emit-value
        clearable
      >
        <template #item="{ item }">
          <span class="flex min-w-0 items-center gap-2">
            <ProjectIcon :emoji="(item as Project).emoji" />
            <span class="truncate">{{ (item as Project).name }}</span>
            <AppIcon
              v-if="(item as Project).is_private"
              :icon="Lock"
              size="xs"
              class="shrink-0 text-muted-foreground"
              label="Приватный"
            />
          </span>
        </template>
      </AppSelect>

      <div class="flex flex-col gap-2">
        <span class="text-sm font-medium">Доступ</span>
        <VisibilityChoice v-model="visibility" />
      </div>
    </div>
    <template #footer>
      <AppTemplateActions
        class="w-full sm:w-auto"
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          {
            label: audio.length ? 'Загрузить' : 'Нечего загружать',
            icon: Upload,
            disabled: !audio.length,
            action: confirm,
          },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { FileAudio, Lock, Upload } from '@lucide/vue'
import type { RecordingVisibility } from '~/shared/api/generated'
import ProjectIcon from '~/features/project/components/ProjectIcon.vue'
import { projectResource, type Project } from '~/features/project/resources/project'
import { isAudioFile, UPLOAD_MAX_BYTES } from '../../utils/audioUpload'
import { useUploadStore } from '../../stores/useUploadStore'
import VisibilityChoice from '../VisibilityChoice.vue'

const props = defineProps<{
  files: File[]
  defaultProjectId?: string | null
  defaultVisibility?: RecordingVisibility
}>()
const open = defineModel<boolean>({ default: false })

const uploads = useUploadStore()
const projectId = ref<string | null>(null)
const visibility = ref<RecordingVisibility>('organization')

const skipped = computed(() => props.files.filter((file) => !isAudioFile(file)))
const tooLarge = computed(() => props.files.filter((file) => isAudioFile(file) && file.size > UPLOAD_MAX_BYTES))
const audio = computed(() =>
  props.files.filter((file) => isAudioFile(file) && file.size > 0 && file.size <= UPLOAD_MAX_BYTES),
)

watch(open, (value) => {
  if (!value) return
  projectId.value = props.defaultProjectId ?? null
  visibility.value = props.defaultVisibility ?? 'organization'
})

const confirm = () => {
  uploads.add(audio.value, { projectId: projectId.value, visibility: visibility.value })
  open.value = false
}

const formatBytes = (bytes: number) => {
  if (bytes < 1024 ** 2) return `${Math.max(1, Math.round(bytes / 1024))} КБ`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1).replace('.', ',')} МБ`
  return `${(bytes / 1024 ** 3).toFixed(2).replace('.', ',')} ГБ`
}
</script>
