<template>
  <AppPopover
    v-model:open="open"
    label="Выбор проекта"
    content-class="w-72 p-0"
  >
    <template #trigger>
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
    </template>
    <div class="flex flex-col">
      <div class="border-b border-border p-1.5">
        <AppInput
          v-model="search"
          is-search
          :debounce="200"
          size="sm"
          variant="ghost"
          placeholder="Найти проект"
          aria-label="Найти проект"
          autofocus
        />
      </div>
      <div class="max-h-72 overflow-y-auto p-1.5">
        <button
          v-if="project"
          type="button"
          class="flex min-h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-muted-foreground outline-none hover:bg-accent focus-visible:bg-accent max-md:min-h-11"
          @click="choose(null)"
        >
          <AppIcon
            :icon="X"
            size="sm"
          />
          Убрать из проекта
        </button>
        <button
          v-for="item in items"
          :key="item.id"
          type="button"
          class="flex min-h-9 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent max-md:min-h-11"
          :aria-pressed="item.id === project?.id"
          @click="choose(item)"
        >
          <ProjectIcon :emoji="item.emoji" />
          <span class="min-w-0 flex-1 truncate">{{ item.name }}</span>
          <AppIcon
            v-if="item.is_private"
            :icon="Lock"
            size="xs"
            class="shrink-0 text-muted-foreground"
            label="Приватный"
          />
          <AppIcon
            v-if="item.id === project?.id"
            :icon="Check"
            size="sm"
            class="shrink-0"
          />
        </button>
        <AppLoadingIndicator
          v-if="isLoading && !items.length"
          fluid
          size="md"
          class="p-3"
        />
        <p
          v-else-if="!items.length"
          class="px-2 py-4 text-center text-xs text-muted-foreground"
        >
          {{ search ? 'Ничего не найдено' : 'Проектов пока нет' }}
        </p>
      </div>
    </div>
  </AppPopover>
</template>

<script setup lang="ts">
import { Check, Lock, X } from '@lucide/vue'
import { useResourceList } from '~/shared/api/useResource'
import ProjectIcon from '~/features/project/components/ProjectIcon.vue'
import { projectResource, type Project, type ProjectBrief } from '~/features/project/resources/project'

defineProps<{ project: ProjectBrief | null }>()
const emit = defineEmits<{ change: [project: ProjectBrief | null] }>()

const open = ref(false)
const search = ref('')
const { items, isLoading } = useResourceList<Project>(projectResource, {
  params: () => ({ name: search.value.trim() || undefined, archived: false }),
  enabled: open,
})

const choose = (item: Project | null) => {
  open.value = false
  emit('change', item ? { id: item.id, name: item.name, emoji: item.emoji, is_private: item.is_private } : null)
}
</script>
