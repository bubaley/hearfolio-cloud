<template>
  <section
    aria-label="Записи проекта"
    class="flex flex-col gap-2"
  >
    <h2 class="text-sm font-medium text-muted-foreground">Записи</h2>
    <!-- The list brings its own gutters (sticky toolbar, row hover); pull it to the article edges. -->
    <RecordingList
      :fixed="{ project_id: projectId }"
      class="-mx-3 md:-mx-4"
    />
  </section>
</template>

<script setup lang="ts">
import RecordingList from '~/features/recording/components/list/RecordingList.vue'

defineProps<{ projectId: string }>()
</script>
