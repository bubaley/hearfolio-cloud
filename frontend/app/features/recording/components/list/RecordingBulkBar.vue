<template>
  <div
    class="flex h-11 items-center gap-1.5 rounded-md bg-accent px-2 md:h-control-md"
    role="toolbar"
    aria-label="Действия с выбранными записями"
  >
    <AppButton
      variant="ghost"
      size="icon"
      text-variant="muted"
      class="size-11 shrink-0 md:size-control-sm"
      :icon="X"
      aria-label="Снять выделение"
      title="Снять выделение (Esc)"
      @click="emit('clear')"
    />
    <span class="min-w-0 flex-1 truncate text-sm font-medium">Выбрано: {{ selected.length }}</span>
    <ProjectPicker
      :allow-remove="selected.some((item) => item.project)"
      align="end"
      @change="(project) => run(() => bulk.moveToProject(selected, project))"
    >
      <template #trigger>
        <AppButton
          variant="ghost"
          size="sm"
          :icon="FolderInput"
          :label="wide ? 'В проект' : undefined"
          aria-label="Перенести в проект"
          class="shrink-0 max-md:size-11"
        />
      </template>
    </ProjectPicker>
    <TagPicker
      :tags="commonTags"
      align="end"
      @change="onTags"
    >
      <template #trigger>
        <AppButton
          variant="ghost"
          size="sm"
          :icon="Tags"
          :label="wide ? 'Теги' : undefined"
          aria-label="Изменить теги"
          class="shrink-0 max-md:size-11"
        />
      </template>
    </TagPicker>
    <AppButton
      variant="ghost"
      size="sm"
      :icon="Trash2"
      :label="wide ? 'Удалить' : undefined"
      aria-label="Удалить выбранные"
      class="shrink-0 text-destructive max-md:size-11"
      @click="deleteOpen = true"
    />
    <AppConfirmModal
      v-model="deleteOpen"
      :title="deletable.length === 1 ? 'Удалить запись?' : `Удалить ${recordingsLabel(deletable.length)}?`"
      :subtitle="deleteText"
      confirm-text="Удалить"
      :confirm-props="{ variant: 'destructive', disabled: !deletable.length }"
      :confirm="confirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { useMediaQuery } from '@vueuse/core'
import { FolderInput, Tags, Trash2, X } from '@lucide/vue'
import { pluralize } from '~/features/project/composables/projectLabels'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import type { Recording, TagBrief } from '../../resources/recording'
import { daysLabel, useTrashDays } from '../../composables/useRecordingMutations'
import { useRecordingBulk } from '../../composables/useRecordingBulk'
import ProjectPicker from '../detail/ProjectPicker.vue'
import TagPicker from '../detail/TagPicker.vue'

/** «Выбрано N» over the list: move into a project, add or remove tags, delete (what the caller may delete). */
const props = defineProps<{ selected: Recording[] }>()
const emit = defineEmits<{ clear: [] }>()

const bulk = useRecordingBulk()
const { user } = useSession()
const { isAdmin } = useOrganizationRole()
const wide = useMediaQuery('(min-width: 768px)')
const deleteOpen = ref(false)
const trashDays = useTrashDays()

const recordingsLabel = (count: number) => pluralize(count, ['запись', 'записи', 'записей'])

const run = async (task: () => Promise<unknown>) => {
  await task()
  emit('clear')
}

// Tags every selected recording has: unchecking one removes it from all, checking a new one adds it to all.
const commonTags = computed<TagBrief[]>(() => {
  const [first, ...rest] = props.selected
  if (!first) return []
  return first.tags.filter((tag) => rest.every((item) => item.tags.some((own) => own.id === tag.id)))
})
const onTags = (tags: TagBrief[]) => {
  const before = new Set(commonTags.value.map((tag) => tag.id))
  const after = new Set(tags.map((tag) => tag.id))
  const added = tags.filter((tag) => !before.has(tag.id))
  const removed = commonTags.value.filter((tag) => !after.has(tag.id))
  if (added.length || removed.length) void bulk.changeTags(props.selected, added, removed)
}

// Delete: the author or an org admin (docs/product.md → Recording permissions).
const deletable = computed(() =>
  props.selected.filter((item) => isAdmin.value || item.created_by_id === user.value?.id),
)
const deleteText = computed(() => {
  const skipped = props.selected.length - deletable.value.length
  const base = `Записи попадут в корзину: их можно восстановить в течение ${daysLabel(trashDays.value)}, потом они удалятся навсегда вместе с аудио`
  if (!deletable.value.length) return 'Удалить запись может только её автор или администратор'
  return skipped
    ? `${base}. Пропустим ${recordingsLabel(skipped)}: их может удалить только автор или администратор`
    : base
})
const confirmDelete = () => run(() => bulk.removeMany(deletable.value))
</script>
