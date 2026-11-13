<template>
  <div
    class="@container relative flex min-h-full flex-col"
    @dragenter="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave="onDragLeave"
    @drop.prevent="onDrop"
  >
    <div class="sticky top-0 z-10 bg-background px-3 pt-1 pb-3 md:px-4">
      <RecordingListToolbar
        :fixed="fixed"
        @upload="pickFiles"
      />
    </div>

    <div class="flex flex-1 flex-col px-1 pb-10 md:px-2">
      <div
        v-if="error && !items.length"
        class="px-2 pt-2"
      >
        <AppAlert
          tone="destructive"
          title="Не удалось загрузить записи"
          description="Проверьте подключение и попробуйте ещё раз"
        >
          <AppTextButton
            label="Повторить"
            weight="medium"
            @click="refetch()"
          />
        </AppAlert>
      </div>

      <div
        v-else-if="isLoading && !items.length"
        class="flex flex-col gap-1 px-2 pt-1"
        aria-busy="true"
        aria-label="Загрузка записей"
      >
        <AppSkeleton class="mb-2 h-3 w-20" />
        <div
          v-for="row in 8"
          :key="row"
          class="flex h-11 items-center gap-3"
        >
          <AppSkeleton class="size-4 shrink-0" />
          <AppSkeleton
            class="h-3.5"
            :class="row % 3 ? 'w-1/2' : 'w-2/3'"
          />
          <div class="flex-1" />
          <AppSkeleton class="hidden h-3 w-24 md:block" />
          <AppSkeleton
            circle
            class="size-5 shrink-0"
          />
        </div>
      </div>

      <div
        v-else-if="!items.length"
        class="flex flex-1 items-center justify-center px-3 py-10"
      >
        <div class="w-full max-w-sm">
          <AppResultState
            v-if="filters.active.value"
            :icon="SearchX"
            title="Ничего не найдено"
            :description="
              filters.search.value
                ? 'Попробуйте другие слова: поиск идёт по названию и тексту расшифровки'
                : 'Под эти фильтры не подходит ни одна запись'
            "
          >
            <template #actions>
              <AppButton
                variant="outline"
                label="Сбросить фильтры"
                @click="filters.reset()"
              />
            </template>
          </AppResultState>
          <AppResultState
            v-else
            :icon="empty.icon"
            :title="empty.title"
            :description="empty.description"
          >
            <template #actions>
              <AppButton
                :icon="Upload"
                label="Загрузить файл"
                @click="pickFiles"
              />
              <slot name="empty-actions" />
            </template>
          </AppResultState>
        </div>
      </div>

      <template v-else>
        <section
          v-for="group in groups"
          :key="group.key"
          :aria-label="group.label"
          class="mb-3"
        >
          <h2 class="px-2 pt-2 pb-1 text-xs font-medium text-muted-foreground">{{ group.label }}</h2>
          <RecordingRow
            v-for="row in group.rows"
            :key="row.recording.id"
            :recording="row.recording"
            :time="row.time"
            :hide-project="Boolean(fixed.project_id)"
          />
        </section>
        <AppInfiniteScroll
          :has-more="Boolean(hasNextPage)"
          :loading="isLoading"
          :error="Boolean(error)"
          :request-key="params"
          @load="loadNextPage()"
          @retry="loadNextPage()"
        />
      </template>
    </div>

    <div
      v-if="dragging"
      class="pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded-xl border-2 border-dashed border-border-strong bg-background/85"
    >
      <div class="flex flex-col items-center gap-2 text-center">
        <AppIcon
          :icon="Upload"
          size="lg"
        />
        <p class="text-sm font-medium">Отпустите, чтобы загрузить</p>
        <p class="text-xs text-muted-foreground">Аудиофайлы до 10 ГБ</p>
      </div>
    </div>

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
      :default-project-id="fixed.project_id ?? filters.projectId.value"
      :default-visibility="fixed.personal ? 'personal' : 'organization'"
    />
  </div>
</template>

<script setup lang="ts">
import { AudioLines, Lock, SearchX, Upload } from '@lucide/vue'
import { useResourceList } from '~/shared/api/useResource'
import { recordingResource, type Recording, type RecordingFilters } from '../../resources/recording'
import { useRecordingFilters } from '../../composables/useRecordingFilters'
import { useRecordingGroups } from '../../composables/useRecordingGroups'
import { AUDIO_ACCEPT } from '../../utils/audioUpload'
import UploadModal from '../upload/UploadModal.vue'
import RecordingListToolbar from './RecordingListToolbar.vue'
import RecordingRow from './RecordingRow.vue'

/**
 * The recordings list of a screen: filters in the URL, rows grouped by day, infinite scroll, drag & drop upload.
 * `fixed` scopes it (`{ personal: true }` for «Личные», `{ project_id }` on a project page); those filters are
 * neither shown nor editable, and a project scope becomes the upload default.
 */
const props = withDefaults(defineProps<{ fixed?: RecordingFilters }>(), { fixed: () => ({}) })

const filters = useRecordingFilters(() => props.fixed)
const params = filters.params

const { items, hasNextPage, loadNextPage, isLoading, error, refetch } = useResourceList<Recording>(recordingResource, {
  params,
  pageSize: 40,
})
const groups = useRecordingGroups(items)

const empty = computed(() =>
  props.fixed.personal
    ? {
        icon: Lock,
        title: 'Личных записей пока нет',
        description:
          'Личные записи видите только вы. Выберите «Личная» при записи в приложении Hearfolio или при загрузке файла',
      }
    : props.fixed.project_id
      ? {
          icon: AudioLines,
          title: 'В проекте пока нет записей',
          description: 'Выберите этот проект при записи в приложении Hearfolio или загрузите файл сюда',
        }
      : {
          icon: AudioLines,
          title: 'Здесь появятся записи',
          description:
            'Запишите в приложении Hearfolio или загрузите файл — расшифровка и саммари появятся здесь через минуту',
        },
)

const fileInput = ref<HTMLInputElement>()
const uploadOpen = ref(false)
const pendingFiles = shallowRef<File[]>([])

const pickFiles = () => fileInput.value?.click()
const startUpload = (files: File[]) => {
  if (!files.length) return
  pendingFiles.value = files
  uploadOpen.value = true
}
const onPicked = (event: Event) => {
  const input = event.target as HTMLInputElement
  startUpload([...(input.files ?? [])])
  input.value = ''
}

// dragenter/dragleave fire for every child; a counter tells when the pointer really left the list.
const dragging = ref(false)
let depth = 0
const hasFiles = (event: DragEvent) => [...(event.dataTransfer?.types ?? [])].includes('Files')
const onDragEnter = (event: DragEvent) => {
  if (!hasFiles(event)) return
  depth++
  dragging.value = true
}
const onDragOver = (event: DragEvent) => {
  if (hasFiles(event) && event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}
const onDragLeave = (event: DragEvent) => {
  if (!hasFiles(event)) return
  depth = Math.max(0, depth - 1)
  if (!depth) dragging.value = false
}
const onDrop = (event: DragEvent) => {
  depth = 0
  dragging.value = false
  startUpload([...(event.dataTransfer?.files ?? [])])
}

defineExpose({ pickFiles })
</script>
