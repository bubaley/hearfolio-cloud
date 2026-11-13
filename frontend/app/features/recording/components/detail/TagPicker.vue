<template>
  <AppPopover
    v-model:open="open"
    label="Выбор тегов"
    :align="align"
    content-class="w-72 p-0"
  >
    <template #trigger>
      <slot
        name="trigger"
        :open="open"
      >
        <button
          type="button"
          class="flex min-h-9 w-full min-w-0 flex-wrap items-center gap-1 rounded-md px-2 py-1.5 text-left text-sm transition-colors outline-none hover:bg-field-hover focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-11"
          :aria-label="tags.length ? `Теги: ${tags.map((tag) => tag.name).join(', ')}. Изменить` : 'Добавить теги'"
        >
          <TagChip
            v-for="tag in tags"
            :key="tag.id"
            :name="tag.name"
            :color="tag.color"
            class="max-w-40"
          />
          <span
            v-if="!tags.length"
            class="text-muted-foreground"
            >Добавить теги</span
          >
        </button>
      </slot>
    </template>
    <div
      class="flex flex-col"
      @keydown.enter.prevent="onEnter"
    >
      <div class="flex flex-wrap items-center gap-1 border-b border-border p-1.5">
        <AppInput
          v-model="search"
          size="sm"
          variant="ghost"
          placeholder="Найти или создать тег"
          aria-label="Найти или создать тег"
          autofocus
          class="min-w-0 flex-1"
        />
      </div>
      <div class="max-h-72 overflow-y-auto p-1.5">
        <p class="px-2 pt-1 pb-1.5 text-xs text-muted-foreground">Выберите тег или создайте новый</p>
        <button
          v-for="tag in visible"
          :key="tag.id"
          type="button"
          role="checkbox"
          :aria-checked="selectedIds.has(tag.id)"
          class="flex min-h-9 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left outline-none hover:bg-accent focus-visible:bg-accent max-md:min-h-11"
          @click="toggle(tag)"
        >
          <TagChip
            :name="tag.name"
            :color="tag.color"
          />
          <span class="flex-1" />
          <AppIcon
            v-if="selectedIds.has(tag.id)"
            :icon="Check"
            size="sm"
            class="shrink-0"
          />
        </button>
        <button
          v-if="canCreate"
          type="button"
          class="flex min-h-9 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent max-md:min-h-11"
          :disabled="creating"
          @click="createTag"
        >
          <AppIcon
            :icon="creating ? undefined : Plus"
            :loading="creating"
            size="sm"
            class="shrink-0 text-muted-foreground"
          />
          <span class="truncate">Создать «{{ normalized }}»</span>
        </button>
        <AppLoadingIndicator
          v-if="isLoading && !items.length"
          fluid
          size="md"
          class="p-3"
        />
        <p
          v-else-if="!visible.length && !canCreate"
          class="px-2 py-4 text-center text-xs text-muted-foreground"
        >
          Тегов пока нет — введите название, чтобы создать
        </p>
      </div>
    </div>
  </AppPopover>
</template>

<script setup lang="ts">
import { useQueryCache } from '@pinia/colada'
import { Check, Plus } from '@lucide/vue'
import { tagsCreate, tagsList } from '~/shared/api/generated'
import { isApiError } from '~/shared/api/client'
import { useApiClient, useResourceList } from '~/shared/api/useResource'
import type { TagBrief } from '../../resources/recording'
import TagChip from '~/features/tag/components/TagChip.vue'
import { tagResource, type Tag } from '~/features/tag/resources/tag'

/** Tag multi-select; `#trigger` replaces the property button (bulk actions pass the tags common to the selection). */
const props = withDefaults(defineProps<{ tags: TagBrief[]; align?: 'start' | 'center' | 'end' }>(), {
  align: 'start',
})
const emit = defineEmits<{ change: [tags: TagBrief[]] }>()

const client = useApiClient()
const queryCache = useQueryCache()
const toast = useToast()
const open = ref(false)
const search = ref('')
const creating = ref(false)

// All tags of the organization are few (AI caps them per recording); filter locally for instant feedback.
const { items, isLoading } = useResourceList<Tag>(tagResource, { pageSize: 200, enabled: open })

const normalized = computed(() => search.value.trim().replace(/\s+/g, ' ').slice(0, 64))
const key = (name: string) => name.toLocaleLowerCase('ru')
const visible = computed(() => {
  const query = key(normalized.value)
  return query ? items.value.filter((tag) => key(tag.name).includes(query)) : items.value
})
const canCreate = computed(
  () => Boolean(normalized.value) && !items.value.some((tag) => key(tag.name) === key(normalized.value)),
)
const selectedIds = computed(() => new Set(props.tags.map((tag) => tag.id)))

const brief = (tag: Tag | TagBrief): TagBrief => ({ id: tag.id, name: tag.name, color: tag.color })

const toggle = (tag: Tag | TagBrief) => {
  emit(
    'change',
    selectedIds.value.has(tag.id) ? props.tags.filter((item) => item.id !== tag.id) : [...props.tags, brief(tag)],
  )
}

const createTag = async () => {
  if (!canCreate.value || creating.value) return
  creating.value = true
  const name = normalized.value
  try {
    let tag: Tag | undefined
    try {
      tag = (await tagsCreate({ client, throwOnError: true, body: { name } })).data
    } catch (error) {
      // Someone created it meanwhile: use theirs.
      if (!isApiError(error, 409)) throw error
      const { data } = await tagsList({ client, throwOnError: true, query: { name } })
      tag = data.data.find((item) => key(item.name) === key(name))
      if (!tag) throw error
    }
    search.value = ''
    void queryCache.invalidateQueries({ key: [tagResource.key] })
    toggle(tag)
  } catch {
    toast.error('Не удалось создать тег')
  } finally {
    creating.value = false
  }
}

const onEnter = () => {
  if (canCreate.value) void createTag()
  else if (visible.value.length === 1) toggle(visible.value[0]!)
}
</script>
