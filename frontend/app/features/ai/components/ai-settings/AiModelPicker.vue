<template>
  <AppSettingRow
    :label="label"
    :description="description"
    stacked
  >
    <div class="flex w-full flex-col gap-3">
      <AppSelect
        :model-value="models"
        :source="source"
        multiple
        emit-value
        option-value="id"
        option-label="id"
        :disabled="disabled"
        :placeholder="configured ? 'Найдите модель по названию' : 'Сначала подключите API'"
        :aria-label="label"
        @update:model-value="(value: string[]) => emit('update:models', value ?? [])"
      >
        <template #item="{ item }">
          <span class="flex min-w-0 flex-col">
            <span class="truncate">{{ item.name || item.id }}</span>
            <span class="truncate text-xs text-muted-foreground">{{ item.id }}{{ priceHint(item) }}</span>
          </span>
        </template>
        <!-- The trigger keeps one line (a count); the chosen models are listed under it. Chips inside the trigger
             made it grow with every tick and pushed the open list away from the pointer. -->
        <template #selection="{ selected }">
          <span class="truncate">Выбрано: {{ selected.length }}</span>
        </template>
        <template #empty>{{ configured ? 'Ничего не нашли' : 'Каталог появится после подключения' }}</template>
      </AppSelect>
      <ul
        v-if="models.length"
        class="flex flex-wrap gap-1.5"
        :aria-label="`${label}: выбранные модели`"
      >
        <li
          v-for="id in models"
          :key="id"
          class="inline-flex max-w-full items-center gap-1 rounded-sm bg-secondary py-0.5 pr-1 pl-2 text-xs"
        >
          <span class="min-w-0 truncate">{{ id }}</span>
          <button
            type="button"
            class="grid size-5 shrink-0 place-items-center rounded-sm text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none max-md:size-8"
            :disabled="disabled"
            :aria-label="`Убрать: ${id}`"
            @click="
              emit(
                'update:models',
                models.filter((item) => item !== id),
              )
            "
          >
            <AppIcon
              :icon="X"
              size="xs"
            />
          </button>
        </li>
      </ul>
      <div class="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
        <span class="shrink-0 text-sm text-muted-foreground">По умолчанию</span>
        <AppSelect
          :model-value="defaultModel"
          :options="defaultOptions"
          option-value="id"
          option-label="id"
          emit-value
          class="min-w-0 flex-1 sm:max-w-sm"
          :disabled="disabled || !models.length"
          :placeholder="models.length ? 'Выберите модель' : 'Добавьте модели выше'"
          aria-label="Модель по умолчанию"
          @update:model-value="(value: string | null) => value && emit('update:default', value)"
        />
      </div>
    </div>
  </AppSettingRow>
</template>

<script setup lang="ts">
import { X } from '@lucide/vue'
import type { AiModelKind } from '~/shared/api/generated'
import { aiModelSource, type AiModel } from '../../composables/useAiSettings'

const props = defineProps<{
  label: string
  description?: string
  kind: AiModelKind
  models: string[]
  defaultModel: string | null
  configured: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:models': [models: string[]]; 'update:default': [model: string] }>()

const source = aiModelSource(props.kind)
const defaultOptions = computed(() => props.models.map((id) => ({ id })))

// OpenRouter prices are per token in USD; per million reads better.
const priceHint = (item: AiModel) => {
  const price = Number(item.prompt_price)
  if (!item.prompt_price || !Number.isFinite(price)) return ''
  return price === 0 ? ' · бесплатно' : ` · $${(price * 1_000_000).toFixed(2)} / 1M`
}
</script>
