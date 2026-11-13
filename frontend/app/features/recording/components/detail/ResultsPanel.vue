<template>
  <div class="flex flex-col gap-4">
    <div class="flex items-center gap-2">
      <p class="min-w-0 flex-1 text-xs text-muted-foreground">
        {{
          transcribed
            ? 'Саммари создаются по шаблонам организации или по вашему запросу'
            : 'Саммари можно создать после расшифровки'
        }}
      </p>
      <AppButton
        size="sm"
        variant="outline"
        :icon="Sparkles"
        label="Создать саммари"
        class="shrink-0 max-md:h-11"
        :disabled="!transcribed"
        @click="createOpen = true"
      />
    </div>

    <AppAlert
      v-if="error && !results.length"
      tone="destructive"
      title="Не удалось загрузить саммари"
    >
      <AppTextButton
        label="Повторить"
        weight="medium"
        @click="refetch()"
      />
    </AppAlert>
    <div
      v-else-if="isLoading && !results.length"
      class="flex flex-col gap-3"
    >
      <AppSkeleton
        v-for="row in 2"
        :key="row"
        :lines="4"
      />
    </div>
    <div
      v-else-if="!results.length"
      class="py-6"
    >
      <AppResultState
        :icon="Sparkles"
        title="Саммари пока нет"
        :description="
          transcribed
            ? 'Выберите шаблоны — например «Кратко» или «Задачи и ответственные» — и модель соберёт главное'
            : 'Когда расшифровка будет готова, здесь можно будет собрать главное из записи'
        "
      />
    </div>

    <article
      v-for="result in results"
      :key="result.id"
      class="rounded-lg border border-border"
      :aria-label="result.title"
    >
      <header class="flex min-h-11 items-center gap-2 border-b border-border py-1 pr-1 pl-4">
        <h3 class="min-w-0 flex-1 truncate text-sm font-semibold">{{ result.title }}</h3>
        <AppLabel
          v-if="result.status !== 'done'"
          :config="RESULT_STATUS_LABELS[result.status]"
          size="xs"
          variant="soft"
          class="shrink-0"
        />
        <span class="hidden shrink-0 text-xs text-muted-foreground sm:inline">{{ shortModel(result.model) }}</span>
        <AppMenu
          :actions="actionsFor(result)"
          align="end"
        >
          <template #trigger>
            <AppButton
              variant="ghost"
              size="icon"
              text-variant="muted"
              class="size-11 md:size-control-md"
              :icon="Ellipsis"
              :aria-label="`Действия: ${result.title}`"
            />
          </template>
        </AppMenu>
      </header>
      <div class="px-4 py-3">
        <AppMarkdown
          v-if="result.status === 'done'"
          :source="result.content"
        />
        <div
          v-else-if="result.status === 'failed'"
          class="flex flex-col items-start gap-2"
        >
          <p class="text-sm text-destructive">
            {{ processingErrorText(result.error_code, result.error_message) || 'Модель не смогла собрать саммари' }}
          </p>
          <AppButton
            size="sm"
            variant="outline"
            :icon="RotateCcw"
            label="Повторить"
            @click="regenerate(result)"
          />
        </div>
        <div
          v-else
          class="flex flex-col gap-3"
          role="status"
        >
          <p class="text-xs text-muted-foreground">
            {{ result.status === 'running' ? 'Модель пишет саммари…' : 'Ждёт своей очереди…' }}
          </p>
          <AppSkeleton :lines="3" />
        </div>
      </div>
    </article>

    <CreateResultModal
      v-model="createOpen"
      :create="create"
    />
    <AppConfirmModal
      v-model="confirmOpen"
      title="Удалить саммари?"
      :subtitle="pendingDelete ? `«${pendingDelete.title}» исчезнет у всех участников` : ''"
      confirm-text="Удалить"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="confirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { Copy, Ellipsis, RotateCcw, Sparkles, Trash2 } from '@lucide/vue'
import { useClipboard } from '@vueuse/core'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import type { RecordingDetail } from '../../resources/recording'
import type { RecordingResult, useRecordingResults } from '../../composables/useRecordingDetail'
import { processingErrorText, RESULT_STATUS_LABELS } from '../../composables/useRecordingLabels'
import CreateResultModal from './CreateResultModal.vue'

const props = defineProps<{
  recording: RecordingDetail
  state: ReturnType<typeof useRecordingResults>
  userId: string | null
  isAdmin: boolean
}>()

const { results, isLoading, error, refetch, regenerate, remove, create } = props.state
const transcribed = computed(() => props.recording.status === 'transcribed')
const createOpen = ref(false)
const confirmOpen = ref(false)
const pendingDelete = ref<RecordingResult | null>(null)
const { copy } = useClipboard({ legacy: true })
const toast = useToast()

const shortModel = (model: string) => model.split('/').pop() ?? model

// Own results; automatic ones also by the recording's author; anything for org admins (docs/product.md).
const canDelete = (result: RecordingResult) =>
  props.isAdmin ||
  (Boolean(props.userId) &&
    (result.created_by_id === props.userId ||
      (!result.created_by_id && props.recording.created_by_id === props.userId)))

const actionsFor = (result: RecordingResult): AppMenuAction[] => [
  {
    label: 'Копировать текст',
    icon: Copy,
    hidden: result.status !== 'done',
    action: async () => {
      await copy(result.content)
      toast.default('Саммари скопировано')
    },
  },
  {
    label: 'Создать заново',
    icon: RotateCcw,
    disabled: !transcribed.value,
    action: () => regenerate(result),
  },
  {
    label: 'Удалить',
    icon: Trash2,
    destructive: true,
    separatorBefore: true,
    hidden: !canDelete(result),
    action: () => {
      pendingDelete.value = result
      confirmOpen.value = true
    },
  },
]

const confirmDelete = async () => {
  if (pendingDelete.value) await remove(pendingDelete.value)
}
</script>
