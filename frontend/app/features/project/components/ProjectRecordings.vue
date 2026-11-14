<template>
  <section
    aria-label="Записи проекта"
    class="flex flex-col gap-2"
  >
    <h2 class="text-sm font-medium text-muted-foreground">Записи</h2>
    <!-- The list brings its own gutters (sticky toolbar, row hover); pull it to the article edges. -->
    <RecordingList
      ref="list"
      :fixed="{ project_id: projectId }"
      :can-upload="canUpload"
      class="-mx-3 md:-mx-4"
    />
  </section>
</template>

<script setup lang="ts">
import RecordingList from '~/features/recording/components/list/RecordingList.vue'

/** `canUpload: false` for an archived project: no uploads into it until it comes back. */
withDefaults(defineProps<{ projectId: string; canUpload?: boolean }>(), { canUpload: true })

// «Загрузить» sits in the project page header; the list owns the file dialog.
const list = ref<{ pickFiles: () => void }>()
defineExpose({ pickFiles: () => list.value?.pickFiles() })
</script>
