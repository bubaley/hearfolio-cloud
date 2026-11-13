<template>
  <section
    aria-label="Записи проекта"
    class="flex flex-col gap-3"
  >
    <h2 class="text-sm font-medium text-muted-foreground">Записи</h2>
    <!-- Extension point: the recordings list component replaces this link with the list filtered by `projectId`. -->
    <div class="rounded-lg border border-dashed border-border p-6">
      <AppResultState
        :icon="AudioLines"
        title="Записи проекта"
        description="Записи, которые сохранили в этот проект из приложения или веб-версии"
      >
        <template #actions>
          <AppButton
            variant="outline"
            label="Открыть записи проекта"
            :icon="ArrowRight"
            icon-position="end"
            :to="{ path: '/recordings', query: { project_id: projectId } }"
          />
        </template>
      </AppResultState>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ArrowRight, AudioLines } from '@lucide/vue'

defineProps<{ projectId: string }>()
</script>
