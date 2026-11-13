<template>
  <AppPageView
    title="Шаблоны саммари"
    description="Готовые инструкции для саммари. Автоматические создаются для каждой новой записи"
    content-class="px-4 pb-10"
  >
    <template #actions>
      <AppButton
        v-if="isAdmin"
        size="sm"
        label="Новый шаблон"
        :icon="Plus"
        @click="openTemplate(null)"
      />
    </template>
    <div class="flex flex-col gap-3 pt-2">
      <AppAlert
        v-if="error && !items.length"
        tone="destructive"
        title="Не удалось загрузить шаблоны"
      >
        <AppTextButton
          label="Повторить"
          weight="medium"
          @click="refetch()"
        />
      </AppAlert>
      <div
        v-else-if="isLoading && !items.length"
        class="flex flex-col gap-5 py-3"
      >
        <AppSkeleton
          v-for="row in 3"
          :key="row"
          :lines="2"
          class="max-w-md"
        />
      </div>
      <ul v-else-if="items.length">
        <li
          v-for="(template, index) in items"
          :key="template.id"
          class="group flex min-h-16 items-center gap-2 border-b border-border last:border-b-0"
        >
          <button
            type="button"
            class="flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-md py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
            @click="openTemplate(template)"
          >
            <span class="flex min-w-0 items-center gap-2">
              <span class="truncate text-sm font-medium">{{ template.name }}</span>
              <AppBadge
                v-if="template.auto"
                label="Авто"
                tone="primary"
                :icon="Zap"
              />
            </span>
            <span class="line-clamp-1 text-sm text-muted-foreground">{{ templateDescription(template) }}</span>
          </button>
          <template v-if="isAdmin">
            <AppSwitch
              :model-value="template.auto"
              size="lg"
              :aria-label="`Автоматически: ${template.name}`"
              :title="template.auto ? 'Создаётся автоматически' : 'Только вручную'"
              @update:model-value="(value: boolean) => toggleAuto(template, value)"
            />
            <AppMenu
              :actions="rowActions(template, index)"
              align="end"
            >
              <template #trigger>
                <AppButton
                  variant="ghost"
                  size="icon"
                  text-variant="muted"
                  class="size-11 md:size-control-md"
                  :icon="Ellipsis"
                  :aria-label="`Действия: ${template.name}`"
                />
              </template>
            </AppMenu>
          </template>
        </li>
      </ul>
      <div
        v-else
        class="flex flex-col items-start gap-3 py-8"
      >
        <p class="text-sm text-muted-foreground">
          Шаблонов нет. {{ isAdmin ? 'Создайте первый — например, «Кратко» или «Задачи и ответственные»' : '' }}
        </p>
        <AppButton
          v-if="isAdmin"
          variant="outline"
          label="Новый шаблон"
          :icon="Plus"
          @click="openTemplate(null)"
        />
      </div>
    </div>

    <SummaryTemplateModal
      v-model="modalOpen"
      :template="selected"
      :readonly="!isAdmin"
    />
    <AppConfirmModal
      :model-value="Boolean(pendingDelete)"
      title="Удалить шаблон?"
      :subtitle="`«${pendingDelete?.name}» пропадёт из списка. Готовые саммари останутся.`"
      confirm-text="Удалить"
      :confirm-props="{ variant: 'destructive' }"
      :confirm="removeTemplate"
      @update:model-value="(open) => !open && (pendingDelete = null)"
    />
  </AppPageView>
</template>

<script setup lang="ts">
import { useQueryCache } from '@pinia/colada'
import { ArrowDown, ArrowUp, Ellipsis, Pencil, Plus, Trash2, Zap } from '@lucide/vue'
import { summaryTemplatesPartialUpdate } from '~/shared/api/generated'
import { resourceKeys } from '~/shared/api/resource'
import { useApiClient, useResourceList, useResourceMutations } from '~/shared/api/useResource'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import SummaryTemplateModal from '../components/summary-templates/SummaryTemplateModal.vue'
import { summaryTemplateResource, templateDescription, type SummaryTemplate } from '../resources/summaryTemplate'

const { isAdmin } = useOrganizationRole()
const client = useApiClient()
const queryCache = useQueryCache()
const toast = useToast()
const { items, isLoading, error, refetch } = useResourceList(summaryTemplateResource, { pageSize: 100 })
const { save, remove } = useResourceMutations(summaryTemplateResource)

const modalOpen = ref(false)
const selected = ref<SummaryTemplate | null>(null)
const openTemplate = (template: SummaryTemplate | null) => {
  selected.value = template
  modalOpen.value = true
}

const toggleAuto = async (template: SummaryTemplate, auto: boolean) => {
  try {
    await save.mutateAsync({ ...summaryTemplateResource.toForm(template), auto })
  } catch {
    toast.error('Не удалось изменить шаблон')
  }
}

// Swap with the neighbour. Positions may repeat (equal positions sort by creation), so the whole order is
// renumbered when needed; only changed rows are written.
const move = async (index: number, offset: -1 | 1) => {
  const order = [...items.value]
  const target = index + offset
  if (target < 0 || target >= order.length) return
  ;[order[index], order[target]] = [order[target]!, order[index]!]
  const changes = order
    .map((template, position) => ({ template, position }))
    .filter(({ template, position }) => template.position !== position)
  try {
    await Promise.all(
      changes.map(({ template, position }) =>
        summaryTemplatesPartialUpdate({
          client,
          throwOnError: true,
          path: { item_id: template.id },
          body: { position },
        }),
      ),
    )
  } catch {
    toast.error('Не удалось изменить порядок')
  } finally {
    await queryCache.invalidateQueries({ key: resourceKeys(summaryTemplateResource).all })
  }
}

const rowActions = (template: SummaryTemplate, index: number): AppMenuAction[] => [
  { label: 'Изменить', icon: Pencil, action: () => openTemplate(template) },
  { label: 'Выше', icon: ArrowUp, disabled: index === 0, action: () => move(index, -1) },
  { label: 'Ниже', icon: ArrowDown, disabled: index === items.value.length - 1, action: () => move(index, 1) },
  {
    label: 'Удалить',
    icon: Trash2,
    destructive: true,
    separatorBefore: true,
    action: () => {
      pendingDelete.value = template
    },
  },
]

const pendingDelete = ref<SummaryTemplate | null>(null)
const removeTemplate = async () => {
  const template = pendingDelete.value
  if (!template) return
  try {
    await remove.mutateAsync(template.id)
  } catch (reason) {
    toast.error('Не удалось удалить шаблон')
    return
  }
  pendingDelete.value = null
  toast.default('Шаблон удалён')
}
</script>
