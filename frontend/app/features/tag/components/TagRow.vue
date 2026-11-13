<template>
  <li class="flex min-h-12 items-center gap-2 border-b border-border py-1.5 last:border-b-0">
    <form
      v-if="renaming"
      class="min-w-0 flex-1"
      @submit.prevent="submitRename"
    >
      <AppInput
        ref="input"
        v-model="draft"
        size="sm"
        maxlength="64"
        aria-label="Название тега"
        class="max-w-xs"
        @keydown.esc.prevent="renaming = false"
        @blur="submitRename"
      />
    </form>
    <NuxtLink
      v-else
      :to="{ name: 'recordings', query: { tag: tag.id } }"
      class="group/tag -mx-1 flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-md px-1 outline-none hover:bg-field-hover focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
      :aria-label="`Записи с тегом «${tag.name}»${count === undefined ? '' : `: ${recordingsCountLabel(count)}`}`"
    >
      <TagChip
        :name="tag.name"
        :color="tag.color"
      />
      <span
        v-if="count !== undefined"
        class="shrink-0 text-sm text-muted-foreground tabular-nums group-hover/tag:text-foreground"
        >{{ count ? recordingsCountLabel(count) : 'нет записей' }}</span
      >
    </NuxtLink>

    <template v-if="canManage">
      <TagColorPicker
        :model-value="tag.color"
        @update:model-value="(color) => color && emit('update', { color })"
      >
        <template #trigger>
          <AppButton
            variant="ghost"
            size="icon"
            class="size-11 shrink-0 md:size-control-sm"
            :aria-label="`Цвет тега «${tag.name}»`"
            title="Цвет"
          >
            <span
              class="size-3.5 rounded-sm border border-border-strong/30"
              :class="tagChipClass(tag.color)"
            />
          </AppButton>
        </template>
      </TagColorPicker>
      <AppMenu
        :actions="actions"
        content-class="w-64"
      >
        <template #trigger>
          <AppButton
            variant="ghost"
            size="icon"
            text-variant="muted"
            class="size-11 shrink-0 md:size-control-sm"
            :icon="Ellipsis"
            :loading="busy"
            :aria-label="`Действия: ${tag.name}`"
          />
        </template>
      </AppMenu>
    </template>
  </li>
</template>

<script setup lang="ts">
import { Ellipsis, Merge, Pencil, Trash2 } from '@lucide/vue'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import type { Tag, TagColor } from '../resources/tag'
import { tagChipClass } from '../composables/tagColors'
import { recordingsCountLabel } from '../composables/useTagUsage'
import TagChip from './TagChip.vue'
import TagColorPicker from './TagColorPicker.vue'

const props = defineProps<{
  tag: Tag
  canManage: boolean
  busy?: boolean
  canMerge?: boolean
  /** Recordings with the tag the caller can see; undefined while loading. */
  count?: number
}>()
const emit = defineEmits<{ update: [changes: { name?: string; color?: TagColor }]; merge: []; delete: [] }>()

const renaming = ref(false)
const draft = ref('')
const input = ref<{ focus: () => void }>()
const startRename = async () => {
  draft.value = props.tag.name
  renaming.value = true
  await nextTick()
  input.value?.focus()
  if (document.activeElement instanceof HTMLInputElement) document.activeElement.select()
}
const submitRename = () => {
  if (!renaming.value) return
  renaming.value = false
  const name = draft.value.replace(/\s+/g, ' ').trim()
  if (name && name !== props.tag.name) emit('update', { name })
}

const actions = computed<AppMenuAction[]>(() => [
  {
    label: 'Переименовать',
    icon: Pencil,
    // The closing menu returns focus to its trigger; start editing after that or the field blurs at once.
    action: () => {
      setTimeout(() => void startRename(), 200)
    },
  },
  { label: 'Объединить с другим…', icon: Merge, hidden: !props.canMerge, action: () => emit('merge') },
  { label: 'Удалить', icon: Trash2, destructive: true, separatorBefore: true, action: () => emit('delete') },
])
</script>
