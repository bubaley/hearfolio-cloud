<template>
  <AppModal
    v-model="open"
    title="Объединить теги"
    :description="description"
    width="28rem"
  >
    <div class="flex flex-col gap-2">
      <AppInput
        v-model="search"
        is-search
        clearable
        size="sm"
        placeholder="Найти тег"
        aria-label="Поиск тега"
        autofocus
      />
      <div
        v-if="visible.length"
        role="radiogroup"
        aria-label="Тег, в который объединить"
        class="flex max-h-72 flex-col overflow-y-auto"
      >
        <button
          v-for="tag in visible"
          :key="tag.id"
          type="button"
          role="radio"
          :aria-checked="targetId === tag.id"
          class="flex min-h-11 items-center gap-2 rounded-md px-2 text-left outline-none hover:bg-row-hover focus-visible:ring-2 focus-visible:ring-ring md:min-h-9"
          :class="targetId === tag.id && 'bg-accent hover:bg-accent'"
          @click="targetId = tag.id"
        >
          <span class="flex min-w-0 flex-1">
            <TagChip
              :name="tag.name"
              :color="tag.color"
            />
          </span>
          <span
            v-if="countOf?.(tag.id) !== undefined"
            class="shrink-0 text-xs text-muted-foreground tabular-nums"
            >{{ recordingsCountLabel(countOf!(tag.id)!) }}</span
          >
          <AppIcon
            :icon="Check"
            size="xs"
            :class="targetId === tag.id ? 'opacity-100' : 'opacity-0'"
          />
        </button>
      </div>
      <p
        v-else
        class="py-4 text-sm text-muted-foreground"
      >
        {{ search ? `Нет тегов с «${search}»` : 'Других тегов нет' }}
      </p>
    </div>
    <template #footer>
      <AppTemplateActions
        :actions="[
          { label: 'Отмена', variant: 'secondary', action: () => void (open = false) },
          {
            label: 'Объединить',
            loading: mergeState.loading.value,
            disabled: !targetId,
            action: mergeState.execute,
          },
        ]"
      />
    </template>
  </AppModal>
</template>

<script setup lang="ts">
import { Check } from '@lucide/vue'
import type { Tag } from '../resources/tag'
import { recordingsCountLabel } from '../composables/useTagUsage'
import TagChip from './TagChip.vue'

const props = defineProps<{
  source: Tag | null
  tags: Tag[]
  merge: (target: Tag) => Promise<void>
  /** Recordings per tag; undefined while the counts load. */
  countOf?: (tagId: string) => number | undefined
}>()
const open = defineModel<boolean>({ default: false })

const search = ref('')
const targetId = ref<string | null>(null)
watch(open, (value) => {
  if (!value) return
  search.value = ''
  targetId.value = null
})

const description = computed(() => {
  const source = props.source
  if (!source) return undefined
  const count = props.countOf?.(source.id)
  const total = count ? ` (${recordingsCountLabel(count)})` : ''
  return `Все записи с тегом «${source.name}»${total} получат выбранный тег, а «${source.name}» удалится`
})

const candidates = computed(() =>
  props.tags.filter((tag) => tag.id !== props.source?.id).sort((a, b) => a.name.localeCompare(b.name, 'ru')),
)
const visible = computed(() => {
  const query = search.value.trim().toLowerCase()
  return query ? candidates.value.filter((tag) => tag.name.toLowerCase().includes(query)) : candidates.value
})

const mergeState = useActionState(async () => {
  const target = candidates.value.find((tag) => tag.id === targetId.value)
  if (!target) return
  await props.merge(target)
  open.value = false
})
</script>
