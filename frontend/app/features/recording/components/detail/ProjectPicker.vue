<template>
  <AppPopover
    v-model:open="open"
    label="Выбор проекта"
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
          class="flex min-h-9 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left text-sm transition-colors outline-none hover:bg-field-hover focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-11"
          :aria-label="project ? `Проект: ${project.name}. Изменить` : 'Выбрать проект'"
        >
          <template v-if="project">
            <ProjectIcon :emoji="project.emoji" />
            <span class="truncate">{{ project.name }}</span>
            <AppIcon
              v-if="project.is_private"
              :icon="Lock"
              size="xs"
              class="shrink-0 text-muted-foreground"
              label="Приватный проект"
            />
          </template>
          <span
            v-else
            class="text-muted-foreground"
            >Без проекта</span
          >
        </button>
      </slot>
    </template>
    <div class="flex flex-col">
      <div class="border-b border-border p-1.5">
        <AppInput
          v-model="search"
          is-search
          size="sm"
          variant="ghost"
          placeholder="Найти проект"
          aria-label="Найти проект"
          role="combobox"
          aria-expanded="true"
          aria-autocomplete="list"
          :aria-controls="listId"
          :aria-activedescendant="options[active] ? optionId(options[active]!.key) : undefined"
          autofocus
          @keydown="onKeydown"
        />
      </div>
      <div
        :id="listId"
        role="listbox"
        aria-label="Проекты"
        class="max-h-72 overflow-y-auto p-1.5"
      >
        <div
          v-for="(option, index) in options"
          :id="optionId(option.key)"
          :key="option.key"
          role="option"
          :aria-selected="index === active"
          class="flex min-h-9 w-full min-w-0 cursor-pointer items-center gap-2 rounded-md px-2 text-left text-sm max-md:min-h-11"
          :class="[index === active && 'bg-accent', !option.project && 'text-muted-foreground']"
          @mousemove="active = index"
          @click="choose(option.project)"
        >
          <template v-if="option.project">
            <ProjectIcon :emoji="option.project.emoji" />
            <span class="min-w-0 flex-1 truncate">{{ option.project.name }}</span>
            <AppIcon
              v-if="option.project.is_private"
              :icon="Lock"
              size="xs"
              class="shrink-0 text-muted-foreground"
              label="Приватный"
            />
            <AppIcon
              v-if="option.project.id === project?.id"
              :icon="Check"
              size="sm"
              class="shrink-0"
              label="Выбран"
            />
          </template>
          <template v-else>
            <AppIcon
              :icon="X"
              size="sm"
            />
            {{ removeLabel }}
          </template>
        </div>
        <AppLoadingIndicator
          v-if="isLoading && !projects.length"
          fluid
          size="md"
          class="p-3"
        />
        <p
          v-else-if="!projects.length"
          class="px-2 py-4 text-center text-xs text-muted-foreground"
        >
          {{ query ? 'Ничего не найдено' : 'Проектов пока нет' }}
        </p>
      </div>
    </div>
  </AppPopover>
</template>

<script setup lang="ts">
import { refDebounced } from '@vueuse/core'
import { Check, Lock, X } from '@lucide/vue'
import { useResourceList } from '~/shared/api/useResource'
import ProjectIcon from '~/features/project/components/ProjectIcon.vue'
import { projectResource, type Project, type ProjectBrief } from '~/features/project/resources/project'

/**
 * Project combobox: the visible, not archived projects are loaded once and filtered locally (instant, ↑↓ + Enter,
 * the first match is highlighted). Only an organization with more projects than one page searches on the server.
 * `#trigger` replaces the default property button (bulk actions); `allowRemove` adds «Убрать из проекта».
 */
const props = withDefaults(
  defineProps<{
    project?: ProjectBrief | null
    allowRemove?: boolean
    removeLabel?: string
    align?: 'start' | 'center' | 'end'
  }>(),
  { project: null, allowRemove: undefined, removeLabel: 'Убрать из проекта', align: 'start' },
)
const emit = defineEmits<{ change: [project: ProjectBrief | null] }>()

const PAGE_SIZE = 200
const open = ref(false)
const search = ref('')
const query = computed(() => search.value.trim().toLocaleLowerCase('ru'))
const debounced = refDebounced(query, 250)

const all = useResourceList<Project>(projectResource, {
  params: () => ({ archived: false }),
  pageSize: PAGE_SIZE,
  enabled: open,
})
// More than one page: the local list is incomplete, so a typed query goes to the server.
const paginated = computed(() => Boolean(all.hasNextPage.value))
const remote = useResourceList<Project>(projectResource, {
  params: () => ({ archived: false, name: debounced.value }),
  pageSize: 50,
  enabled: () => open.value && paginated.value && Boolean(debounced.value),
})

const projects = computed<Project[]>(() => {
  if (paginated.value && query.value) return remote.items.value
  const sorted = [...all.items.value].sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  return query.value ? sorted.filter((item) => item.name.toLocaleLowerCase('ru').includes(query.value)) : sorted
})
const isLoading = computed(() => all.isLoading.value || (paginated.value && remote.isLoading.value))

type Option = { key: string; project: Project | null }
const canRemove = computed(() => props.allowRemove ?? Boolean(props.project))
const options = computed<Option[]>(() => [
  ...projects.value.map((project) => ({ key: project.id, project })),
  ...(canRemove.value && !query.value ? [{ key: 'none', project: null }] : []),
])

const active = ref(0)
watch([query, open], () => {
  active.value = 0
  search.value = open.value ? search.value : ''
})

const uid = useId()
const listId = `project-picker-${uid}`
const optionId = (key: string) => `${listId}-${key}`

const choose = (item: Project | null) => {
  open.value = false
  emit('change', item ? { id: item.id, name: item.name, emoji: item.emoji, is_private: item.is_private } : null)
}

const onKeydown = (event: KeyboardEvent) => {
  const count = options.value.length
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!count) return
    active.value = (active.value + (event.key === 'ArrowDown' ? 1 : count - 1)) % count
    void nextTick(() =>
      document.getElementById(optionId(options.value[active.value]!.key))?.scrollIntoView({ block: 'nearest' }),
    )
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const option = options.value[active.value]
    if (option) choose(option.project)
  }
}
</script>
