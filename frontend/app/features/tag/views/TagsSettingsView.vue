<template>
  <AppPageView
    title="Теги"
    :description="
      isAdmin
        ? 'Общие теги организации. AI добавляет их к записям сам, вы можете переименовать, перекрасить, объединить или удалить'
        : 'Общие теги организации. Создавать может каждый, менять и удалять — администраторы'
    "
    content-class="px-4 pb-10"
  >
    <div class="flex flex-col gap-4 pt-2">
      <form
        class="flex items-end gap-2"
        @submit.prevent="createState.execute"
      >
        <TagColorPicker v-model="newColor" />
        <AppInput
          v-model="newName"
          label="Новый тег"
          placeholder="Название"
          maxlength="64"
          class="min-w-0 flex-1 sm:max-w-xs"
        />
        <AppButton
          type="submit"
          label="Создать"
          :icon="Plus"
          :loading="createState.loading.value"
          :disabled="!newName.trim()"
        />
      </form>

      <AppInput
        v-if="items.length > 10 || search"
        v-model="search"
        is-search
        clearable
        placeholder="Найти тег"
        aria-label="Поиск тегов"
        class="sm:max-w-xs"
      />

      <AppAlert
        v-if="error && !items.length"
        tone="destructive"
        title="Не удалось загрузить теги"
      >
        <AppTextButton
          label="Повторить"
          weight="medium"
          @click="refetch()"
        />
      </AppAlert>
      <ul
        v-else-if="isLoading && !items.length"
        aria-label="Загрузка"
      >
        <li
          v-for="row in 5"
          :key="row"
          class="flex h-12 items-center border-b border-border last:border-b-0"
        >
          <AppSkeleton class="h-5 w-24" />
        </li>
      </ul>
      <ul v-else-if="visible.length">
        <TagRow
          v-for="tag in visible"
          :key="tag.id"
          :tag="tag"
          :can-manage="isAdmin"
          :can-merge="items.length > 1"
          :busy="busyId === tag.id"
          :count="countOf(tag.id)"
          @update="(changes) => updateTag(tag, changes)"
          @merge="openMerge(tag)"
          @delete="pendingDelete = tag"
        />
      </ul>
      <div
        v-else
        class="py-10"
      >
        <AppResultState
          :icon="TagsIcon"
          :title="search ? 'Ничего не нашли' : 'Тегов пока нет'"
          :description="search ? undefined : 'Создайте первый или дождитесь, пока AI разметит записи'"
        />
      </div>
    </div>

    <TagMergeModal
      v-model="mergeOpen"
      :source="mergeSource"
      :tags="items"
      :merge="mergeTag"
      :count-of="countOf"
    />
    <AppConfirmModal
      :model-value="Boolean(pendingDelete)"
      title="Удалить тег?"
      :subtitle="`Тег «${pendingDelete?.name ?? ''}» снимется со всех записей. Сами записи останутся.`"
      confirm-text="Удалить"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="deleteTag"
      @update:model-value="(value) => !value && (pendingDelete = null)"
    />
  </AppPageView>
</template>

<script setup lang="ts">
import { Plus, Tags as TagsIcon } from '@lucide/vue'
import { useQueryCache } from '@pinia/colada'
import { tagsMerge } from '~/shared/api/generated'
import { invalidateResource, useApiClient, useResourceList, useResourceMutations } from '~/shared/api/useResource'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import { tagResource, type Tag, type TagColor } from '../resources/tag'
import { tagErrorMessage } from '../composables/tagColors'
import TagColorPicker from '../components/TagColorPicker.vue'
import TagMergeModal from '../components/TagMergeModal.vue'
import TagRow from '../components/TagRow.vue'
import { useTagUsage } from '../composables/useTagUsage'

const { isAdmin } = useOrganizationRole()
const { countOf } = useTagUsage()
const toast = useToast()
const client = useApiClient()
const queryCache = useQueryCache()
const setupStore = useSetupStore()

const { items, isLoading, error, refetch, hasNextPage, loadNextPage } = useResourceList(tagResource, {
  pageSize: 200,
  enabled: () => Boolean(setupStore.state.organization),
})
// The screen filters locally, so it needs every tag.
watch(
  () => hasNextPage.value && !isLoading.value,
  (more) => {
    if (more) void loadNextPage()
  },
  { immediate: true },
)
const { save, remove } = useResourceMutations(tagResource)

const search = ref('')
const visible = computed(() => {
  const query = search.value.trim().toLowerCase()
  const sorted = [...items.value].sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  return query ? sorted.filter((tag) => tag.name.toLowerCase().includes(query)) : sorted
})

const newName = ref('')
const newColor = ref<TagColor | null>(null)
const createState = useActionState(async () => {
  if (!newName.value.trim()) return
  try {
    await save.mutateAsync({ id: null, name: newName.value, color: newColor.value })
  } catch (reason) {
    toast.error(tagErrorMessage(reason, 'Не удалось создать тег'))
    return
  }
  toast.default('Тег создан')
  newName.value = ''
  newColor.value = null
})

const busyId = ref<string | null>(null)
const updateTag = async (tag: Tag, changes: { name?: string; color?: TagColor }) => {
  busyId.value = tag.id
  try {
    await save.mutateAsync({ ...tagResource.toForm(tag), ...changes })
    toast.default(changes.name ? 'Тег переименован' : 'Цвет изменён')
  } catch (reason) {
    toast.error(tagErrorMessage(reason, 'Не удалось изменить тег'))
  } finally {
    busyId.value = null
  }
}

const mergeOpen = ref(false)
const mergeSource = ref<Tag | null>(null)
const openMerge = (tag: Tag) => {
  mergeSource.value = tag
  mergeOpen.value = true
}
const mergeTag = async (target: Tag) => {
  const source = mergeSource.value
  if (!source) return
  try {
    await tagsMerge({ client, throwOnError: true, path: { item_id: source.id }, body: { target_id: target.id } })
  } catch (reason) {
    toast.error(tagErrorMessage(reason, 'Не удалось объединить теги'))
    throw reason
  } finally {
    await invalidateResource(queryCache, tagResource)
  }
  toast.default(`«${source.name}» объединён с «${target.name}»`)
}

const pendingDelete = ref<Tag | null>(null)
const deleteTag = async () => {
  const tag = pendingDelete.value
  if (!tag) return
  try {
    await remove.mutateAsync(tag.id)
  } catch (reason) {
    toast.error(tagErrorMessage(reason, 'Не удалось удалить тег'))
    return
  }
  pendingDelete.value = null
  toast.default('Тег удалён')
}
</script>
