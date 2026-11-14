<template>
  <AppPopover
    v-model:open="open"
    label="Публичная ссылка"
    align="end"
    content-class="w-[min(22rem,calc(100vw-24px))] p-0"
  >
    <template #trigger>
      <AppButton
        variant="ghost"
        :icon="link ? Globe : Share2"
        :label="wide ? (link ? 'Опубликовано' : 'Поделиться') : undefined"
        :aria-label="link ? 'Опубликовано по ссылке — настроить' : 'Поделиться'"
        :text-variant="link ? 'base' : 'muted'"
        :class="!wide && 'size-11'"
      />
    </template>

    <div class="flex flex-col">
      <div class="flex items-start gap-3 p-4">
        <div class="flex min-w-0 flex-1 flex-col gap-0.5">
          <span
            id="share-toggle-label"
            class="text-sm font-medium"
            >Публичная ссылка</span
          >
          <span class="text-xs text-muted-foreground">
            {{ link ? 'Любой, у кого есть ссылка, увидит выбранное ниже' : 'Откройте запись по ссылке без входа' }}
          </span>
        </div>
        <AppSwitch
          :model-value="Boolean(link)"
          size="lg"
          :disabled="busy || isLoading"
          aria-labelledby="share-toggle-label"
          @update:model-value="toggle"
        />
      </div>

      <AppSkeleton
        v-if="isLoading"
        :lines="2"
        class="px-4 pb-4"
      />
      <template v-else-if="link">
        <div class="flex items-center gap-2 px-4 pb-3">
          <AppInput
            :model-value="url"
            readonly
            size="sm"
            aria-label="Ссылка"
            class="min-w-0 flex-1"
            @focus="($event.target as HTMLInputElement).select()"
          />
          <AppButton
            size="sm"
            :icon="copied ? Check : Copy"
            :label="copied ? 'Скопировано' : 'Копировать'"
            class="shrink-0 max-md:h-11"
            @click="copyLink"
          />
        </div>

        <div class="flex flex-col gap-0.5 border-t border-border px-2 py-2">
          <p class="px-2 py-1 text-xs font-medium text-muted-foreground">Что увидят по ссылке</p>
          <label
            class="flex min-h-9 cursor-pointer items-center gap-3 rounded-md px-2 hover:bg-field-hover max-md:min-h-11"
          >
            <AppCheckbox
              :model-value="link.include_audio"
              :disabled="busy"
              @update:model-value="(value: boolean) => update({ include_audio: value })"
            />
            <span class="text-sm">Аудио</span>
          </label>
          <label
            class="flex min-h-9 cursor-pointer items-center gap-3 rounded-md px-2 hover:bg-field-hover max-md:min-h-11"
          >
            <AppCheckbox
              :model-value="link.include_transcript"
              :disabled="busy"
              @update:model-value="(value: boolean) => update({ include_transcript: value })"
            />
            <span class="text-sm">Расшифровка</span>
          </label>
          <label
            v-for="result in doneResults"
            :key="result.id"
            class="flex min-h-9 cursor-pointer items-center gap-3 rounded-md px-2 hover:bg-field-hover max-md:min-h-11"
          >
            <AppCheckbox
              :model-value="link.result_ids.includes(result.id)"
              :disabled="busy"
              @update:model-value="(value: boolean) => toggleResult(result.id, value)"
            />
            <span class="min-w-0 truncate text-sm">Саммари «{{ result.title }}»</span>
          </label>
        </div>

        <div class="flex items-center gap-3 border-t border-border px-4 py-3">
          <span class="min-w-0 flex-1 text-xs text-muted-foreground">
            {{ expiryText }}<template v-if="link.views"> · просмотров: {{ link.views }}</template>
          </span>
          <AppMenu
            :actions="expiryActions"
            align="end"
            label="Срок действия"
          >
            <template #trigger>
              <AppButton
                variant="ghost"
                size="sm"
                text-variant="muted"
                :icon="Clock"
                label="Срок"
                class="max-md:h-11"
              />
            </template>
          </AppMenu>
        </div>
      </template>
    </div>
  </AppPopover>
</template>

<script setup lang="ts">
import { useClipboard, useMediaQuery } from '@vueuse/core'
import { Check, Clock, Copy, Globe, Share2 } from '@lucide/vue'
import type { ShareLinkUpsertSchema } from '~/shared/api/generated'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'
import { useRecordingShare, type RecordingResult, type ShareLink } from '../../composables/useRecordingDetail'

const props = defineProps<{ recordingId: string; results: RecordingResult[] }>()

const open = defineModel<boolean>('open', { default: false })
const wide = useMediaQuery('(min-width: 768px)')
// Loaded with the page: the button shows whether the recording is published.
const { link, isLoading, save, revoke } = useRecordingShare(() => props.recordingId, true)
const busy = ref(false)
const { copy, copied } = useClipboard({ legacy: true, copiedDuring: 2000 })
const { formatDate } = useDate()

const doneResults = computed(() => props.results.filter((result) => result.status === 'done'))
const url = computed(() => (link.value ? (link.value.url ?? `${window.location.origin}/s/${link.value.token}`) : ''))

// A summary deleted since the link was saved would make every save fail (400 `unknown_result_ids`): keep only the
// recording's current results.
const knownIds = (ids: string[]) => ids.filter((id) => props.results.some((result) => result.id === id))

const settings = (current: ShareLink): ShareLinkUpsertSchema => ({
  include_audio: current.include_audio,
  include_transcript: current.include_transcript,
  result_ids: knownIds(current.result_ids),
  expires_at: current.expires_at,
})

const run = async (task: () => Promise<unknown>) => {
  busy.value = true
  try {
    await task()
  } catch {
    // The composable already showed the error.
  } finally {
    busy.value = false
  }
}

const toggle = (enabled: boolean) =>
  run(() =>
    enabled
      ? save({
          include_audio: true,
          include_transcript: true,
          result_ids: doneResults.value.map((result) => result.id),
          expires_at: null,
        })
      : revoke(),
  )

const update = (patch: Partial<ShareLinkUpsertSchema>) => {
  const current = link.value
  if (current) void run(() => save({ ...settings(current), ...patch }))
}

const toggleResult = (id: string, enabled: boolean) => {
  const current = link.value
  if (!current) return
  update({
    result_ids: enabled ? [...new Set([...current.result_ids, id])] : current.result_ids.filter((item) => item !== id),
  })
}

const copyLink = async () => {
  await copy(url.value)
}

const expiryText = computed(() => {
  const expires = link.value?.expires_at
  return expires ? `Действует до ${formatDate(expires, { format: 'D MMMM, HH:mm' })}` : 'Бессрочная ссылка'
})

const inDays = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString()
const expiryActions = computed<AppMenuAction[]>(() => [
  { label: 'Без срока', checked: !link.value?.expires_at, action: () => update({ expires_at: null }) },
  { label: '1 день', action: () => update({ expires_at: inDays(1) }) },
  { label: '7 дней', action: () => update({ expires_at: inDays(7) }) },
  { label: '30 дней', action: () => update({ expires_at: inDays(30) }) },
])
</script>
