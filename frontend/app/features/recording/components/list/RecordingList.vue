<template>
  <div
    ref="root"
    class="@container relative flex min-h-full flex-col"
    @dragenter="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- An empty screen without filters teaches with its empty state alone: no toolbar, one «Загрузить». -->
    <div
      v-if="showToolbar"
      class="sticky top-0 z-10 bg-background px-3 pt-1 pb-3 md:px-4"
    >
      <RecordingBulkBar
        v-if="selected.length"
        :selected="selected"
        @clear="clearSelection"
      />
      <RecordingListToolbar
        v-else
        ref="toolbar"
        :fixed="fixed"
        :can-upload="canUpload"
        :trash="trash"
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
                ? trash
                  ? 'В корзине нет записей с такими словами'
                  : 'Попробуйте другие слова: поиск идёт по названию и тексту расшифровки'
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
            <template
              v-if="canUpload"
              #actions
            >
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
        <p
          v-if="params.search"
          class="px-2 pb-1 text-xs text-muted-foreground"
          role="status"
        >
          {{ foundLabel }}
        </p>
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
            :data-id="row.recording.id"
            :recording="row.recording"
            :time="row.time"
            :hide-project="Boolean(fixed.project_id)"
            :query="params.search"
            :selectable="!trash"
            :selected="selectedIds.has(row.recording.id)"
            :selecting="selected.length > 0"
            :trash="trash"
            :trash-days="trashDays"
            :can-manage="canManage(row.recording)"
            @select="(range) => toggleSelect(row.recording, range)"
            @restore="bulk.restoreMany([row.recording.id])"
            @remove="bulk.removeMany([row.recording])"
            @dragstart="(event) => onRowDrag(event, row.recording)"
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
import { useEventListener } from '@vueuse/core'
import { AudioLines, Lock, SearchX, Trash2, Upload } from '@lucide/vue'
import { useResourceList } from '~/shared/api/useResource'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import { pluralize } from '~/features/project/composables/projectLabels'
import { recordingResource, type Recording, type RecordingFilters } from '../../resources/recording'
import { useRecordingFilters } from '../../composables/useRecordingFilters'
import { useRecordingGroups } from '../../composables/useRecordingGroups'
import { useTrashDays } from '../../composables/useRecordingMutations'
import { useRecordingBulk } from '../../composables/useRecordingBulk'
import { AUDIO_ACCEPT } from '../../utils/audioUpload'
import UploadModal from '../upload/UploadModal.vue'
import RecordingBulkBar from './RecordingBulkBar.vue'
import RecordingListToolbar from './RecordingListToolbar.vue'
import RecordingRow from './RecordingRow.vue'

/**
 * The recordings list of a screen: filters in the URL, rows grouped by day, infinite scroll, drag & drop upload,
 * bulk selection and keyboard navigation. `fixed` scopes it (`{ personal: true }` for «Личные», `{ project_id }` on
 * a project page, `{ deleted: true }` for «Корзина»); those filters are neither shown nor editable, and a project
 * scope becomes the upload default. `canUpload: false` (an archived project) hides every upload entry.
 */
const props = withDefaults(defineProps<{ fixed?: RecordingFilters; canUpload?: boolean }>(), {
  fixed: () => ({}),
  canUpload: true,
})

const filters = useRecordingFilters(() => props.fixed)
const params = filters.params
const trash = computed(() => Boolean(props.fixed.deleted))
const canUpload = computed(() => props.canUpload && !trash.value)

const { user } = useSession()
const { isAdmin } = useOrganizationRole()
const bulk = useRecordingBulk()

// The API leaves other users' stalled uploads out of the list; the author still gets theirs (flagged `stalled`).
const { items, total, hasNextPage, loadNextPage, isLoading, error, refetch } = useResourceList<Recording>(
  recordingResource,
  { params, pageSize: 40 },
)
const trashDays = useTrashDays()
const groups = useRecordingGroups(items)

const showToolbar = computed(() =>
  Boolean(items.value.length || filters.active.value || isLoading.value || error.value),
)
// A search answers with the exact number of matches (`meta.total`).
const foundLabel = computed(
  () => `Найдено: ${pluralize(total.value ?? items.value.length, ['запись', 'записи', 'записей'])}`,
)

// Restore in the trash, delete of a stalled upload: the author or an org admin.
const canManage = (recording: Recording) => isAdmin.value || recording.created_by_id === user.value?.id

const empty = computed(() =>
  trash.value
    ? {
        icon: Trash2,
        title: 'Корзина пуста',
        description: `Удалённые записи хранятся здесь ${pluralize(trashDays.value, ['день', 'дня', 'дней'])} — их можно восстановить, потом они удаляются навсегда`,
      }
    : props.fixed.personal
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
            description: canUpload.value
              ? 'Выберите этот проект при записи в приложении Hearfolio или загрузите файл сюда'
              : 'Проект в архиве — верните его, чтобы добавлять записи',
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

const pickFiles = () => {
  if (canUpload.value) fileInput.value?.click()
}
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
  if (!hasFiles(event) || !canUpload.value) return
  depth++
  dragging.value = true
}
const onDragOver = (event: DragEvent) => {
  if (hasFiles(event) && event.dataTransfer) event.dataTransfer.dropEffect = canUpload.value ? 'copy' : 'none'
}
const onDragLeave = (event: DragEvent) => {
  if (!hasFiles(event) || !canUpload.value) return
  depth = Math.max(0, depth - 1)
  if (!depth) dragging.value = false
}
const onDrop = (event: DragEvent) => {
  depth = 0
  dragging.value = false
  if (canUpload.value) startUpload([...(event.dataTransfer?.files ?? [])])
}

// Selection: a click toggles one row, Shift+click selects the range from the last clicked row.
const selectedIds = ref(new Set<string>())
const selected = computed(() => items.value.filter((item) => selectedIds.value.has(item.id)))
let anchor: string | null = null
const toggleSelect = (recording: Recording, range: boolean) => {
  const next = new Set(selectedIds.value)
  const order = items.value.map((item) => item.id)
  const from = anchor ? order.indexOf(anchor) : -1
  if (range && from >= 0) {
    const to = order.indexOf(recording.id)
    for (const id of order.slice(Math.min(from, to), Math.max(from, to) + 1)) next.add(id)
  } else if (next.has(recording.id)) next.delete(recording.id)
  else next.add(recording.id)
  anchor = recording.id
  selectedIds.value = next
}
const clearSelection = () => {
  selectedIds.value = new Set()
  anchor = null
}
// Other filters or another screen: start over.
watch(params, clearSelection)

// Dragging a row (or the selection it belongs to) onto a sidebar project moves it there.
const onRowDrag = (event: DragEvent, recording: Recording) =>
  bulk.startDrag(event, selectedIds.value.has(recording.id) ? selected.value : [recording])

// Keyboard: ↑↓ or j/k move between rows, Enter opens, x selects, Escape clears the selection, «/» focuses the search.
const root = ref<HTMLElement>()
const toolbar = ref<{ focusSearch: () => void }>()
const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) ||
    Boolean(target.closest('[role="dialog"],[role="menu"],[role="listbox"]')))
const rowLinks = () => [...(root.value?.querySelectorAll<HTMLElement>('[data-row-link]') ?? [])]
const focusRow = (links: HTMLElement[], index: number) => links[Math.max(0, Math.min(links.length - 1, index))]?.focus()
useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return
  if (document.querySelector('[role="dialog"][data-state="open"]')) return
  const active = document.activeElement as HTMLElement | null
  const links = rowLinks()
  const index = active ? links.indexOf(active) : -1
  const onBody = !active || active === document.body
  if (event.key === '/') {
    event.preventDefault()
    toolbar.value?.focusSearch()
  } else if (event.key === 'Escape' && selectedIds.value.size) {
    clearSelection()
  } else if ((event.key === 'j' || event.key === 'k') && (index >= 0 || onBody)) {
    event.preventDefault()
    focusRow(links, index < 0 ? 0 : index + (event.key === 'j' ? 1 : -1))
  } else if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && index >= 0) {
    event.preventDefault()
    focusRow(links, index + (event.key === 'ArrowDown' ? 1 : -1))
  } else if (event.key === 'x' && index >= 0) {
    const id = links[index]!.closest('[data-recording-row]')?.getAttribute('data-id')
    const recording = items.value.find((item) => item.id === id)
    if (recording) toggleSelect(recording, event.shiftKey)
  }
})

defineExpose({ pickFiles })
</script>
