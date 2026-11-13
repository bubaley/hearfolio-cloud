<template>
  <div class="flex flex-col gap-2 @3xl:flex-row @3xl:items-center">
    <div class="flex min-w-0 items-center gap-2 @3xl:w-72 @3xl:shrink-0">
      <AppInput
        ref="searchInput"
        v-model="search"
        is-search
        clearable
        :debounce="300"
        :placeholder="trash ? 'Поиск в корзине' : 'Поиск по названию и тексту'"
        aria-keyshortcuts="/"
        aria-label="Поиск записей"
        class="min-w-0 flex-1 max-md:[&_input]:h-11"
      />
      <AppButton
        v-if="canUpload"
        class="size-11 shrink-0 @3xl:hidden"
        size="icon"
        :icon="Upload"
        aria-label="Загрузить файл"
        @click="emit('upload')"
      />
    </div>
    <!-- Phones scroll the filters sideways instead of wrapping them into a wall of controls. -->
    <div
      v-if="!trash"
      class="-mx-3 -my-1 flex min-w-0 [scrollbar-width:none] items-center gap-1.5 overflow-x-auto px-3 py-1 @3xl:mx-0 @3xl:flex-1 @3xl:px-0"
    >
      <AppSelect
        v-if="!hidden.includes('project_id')"
        v-model="projectId"
        :auto-load="Boolean(projectId)"
        :resource="projectResource"
        :query="{ archived: false }"
        search-param="name"
        placeholder="Проект"
        aria-label="Фильтр по проекту"
        size="sm"
        :variant="projectId ? 'active-outline' : 'outline'"
        emit-value
        clearable
        clear-inline
        class="w-36 shrink-0 max-md:[&_[data-app-select-trigger]]:h-11"
      />
      <AppSelect
        v-model="tagId"
        :auto-load="Boolean(tagId)"
        :resource="tagResource"
        search-param="name"
        placeholder="Тег"
        aria-label="Фильтр по тегу"
        size="sm"
        :variant="tagId ? 'active-outline' : 'outline'"
        emit-value
        clearable
        clear-inline
        class="w-32 shrink-0 max-md:[&_[data-app-select-trigger]]:h-11"
      >
        <template #item="{ item }">
          <TagChip
            :name="(item as Tag).name"
            :color="(item as Tag).color"
          />
        </template>
      </AppSelect>
      <AppSelect
        v-if="!hidden.includes('created_by_id') && !fixed.personal"
        v-model="authorId"
        :auto-load="Boolean(authorId)"
        :resource="organizationUserResource"
        :query="{ organization_id: organizationId }"
        :filter="false"
        :option-value="(item: OrganizationUser) => item.user.id"
        :option-label="(item: OrganizationUser) => userDisplayName(item.user)"
        placeholder="Автор"
        aria-label="Фильтр по автору"
        size="sm"
        :variant="authorId ? 'active-outline' : 'outline'"
        emit-value
        clearable
        clear-inline
        class="w-36 shrink-0 max-md:[&_[data-app-select-trigger]]:h-11"
      />
      <AppSelect
        v-model="status"
        :options="STATUS_FILTER_OPTIONS"
        option-value="value"
        option-label="label"
        :filter="false"
        placeholder="Статус"
        aria-label="Фильтр по статусу"
        size="sm"
        :variant="status ? 'active-outline' : 'outline'"
        emit-value
        clearable
        clear-inline
        class="w-32 shrink-0 max-md:[&_[data-app-select-trigger]]:h-11"
      />
      <AppButton
        v-if="active"
        variant="ghost"
        size="sm"
        text-variant="muted"
        label="Сбросить"
        class="shrink-0 max-md:h-11"
        @click="reset()"
      />
      <div class="hidden flex-1 @3xl:block" />
      <AppButton
        v-if="canUpload"
        class="hidden shrink-0 @3xl:inline-flex"
        size="sm"
        :icon="Upload"
        label="Загрузить"
        @click="emit('upload')"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { Upload } from '@lucide/vue'
import { organizationUserResource, type OrganizationUser } from '~/features/organization/resources/organizationUser'
import { projectResource } from '~/features/project/resources/project'
import { tagResource, type Tag } from '~/features/tag/resources/tag'
import { STATUS_FILTER_OPTIONS } from '../../composables/useRecordingLabels'
import type { RecordingFilters } from '../../resources/recording'
import { useRecordingFilters, type RecordingFilterKey } from '../../composables/useRecordingFilters'
import TagChip from '~/features/tag/components/TagChip.vue'

/**
 * Filters live in the URL (`useRecordingFilters`); `fixed` ones belong to the screen and are not shown, and «Автор»
 * makes no sense among one's personal recordings. The trash keeps the search only.
 */
const props = withDefaults(defineProps<{ fixed: RecordingFilters; canUpload?: boolean; trash?: boolean }>(), {
  canUpload: true,
})
const emit = defineEmits<{ upload: [] }>()

const { search, projectId, tagId, authorId, status, active, reset } = useRecordingFilters(() => props.fixed)
const hidden = computed(() => Object.keys(props.fixed) as RecordingFilterKey[])

const searchInput = ref<{ focus: () => void }>()
defineExpose({ focusSearch: () => searchInput.value?.focus() })

const setupStore = useSetupStore()
const organizationId = computed(() => setupStore.state.organization?.id)
</script>
