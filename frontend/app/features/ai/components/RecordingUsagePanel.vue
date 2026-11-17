<template>
  <section
    v-if="usage && usage.lines.length"
    class="flex flex-col gap-2"
    aria-labelledby="ai-usage-title"
  >
    <div class="flex items-baseline justify-between gap-3">
      <h3
        id="ai-usage-title"
        class="text-sm font-medium"
      >
        Расходы на AI
      </h3>
      <span class="text-xs text-muted-foreground">видят только администраторы</span>
    </div>
    <div class="overflow-hidden rounded-lg border border-border">
      <table class="w-full text-sm">
        <tbody>
          <tr
            v-for="line in usage.lines"
            :key="`${line.kind}-${line.result_id ?? ''}`"
            class="border-b border-border"
          >
            <td class="px-3 py-2">
              <div class="font-medium">{{ lineTitle(line) }}</div>
              <div class="text-xs text-muted-foreground">{{ lineDetails(line) }}</div>
            </td>
            <td class="px-3 py-2 text-right align-top whitespace-nowrap tabular-nums">
              {{ formatUsd(line.cost_usd) }}
            </td>
          </tr>
          <tr class="bg-muted/50">
            <td class="px-3 py-2 font-medium">Итого</td>
            <td class="px-3 py-2 text-right font-semibold whitespace-nowrap tabular-nums">
              {{ formatUsd(usage.total.cost_usd) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p
      v-if="usage.total.unknown_cost_requests"
      class="text-xs text-muted-foreground"
    >
      {{ pluralize(usage.total.unknown_cost_requests, ['запрос', 'запроса', 'запросов']) }} без стоимости от провайдера
      — их нет в сумме
    </p>
  </section>
</template>

<script setup lang="ts">
import type { RecordingUsageLineSchema } from '~/shared/api/generated'
import { pluralize } from '~/features/project/composables/projectLabels'
import { useRecordingAiUsage } from '../composables/useAiUsage'
import { formatAudio, formatTokens, formatUsd } from '../utils/usageFormat'

/** Spending on one recording, from the provider's own numbers: transcription, each summary, the small steps. */
const props = defineProps<{ recordingId: string }>()

const { data: usage } = useRecordingAiUsage(() => props.recordingId, true)

const KIND_TITLES: Record<string, string> = {
  transcription: 'Расшифровка',
  title: 'Название',
  tags: 'Теги и проект',
  speakers: 'Имена спикеров',
}

const lineTitle = (line: RecordingUsageLineSchema) =>
  line.kind === 'summary' ? `Саммари «${line.title}»` : (KIND_TITLES[line.kind] ?? line.kind)

const lineDetails = (line: RecordingUsageLineSchema) =>
  [
    line.audio_ms ? `${formatAudio(line.audio_ms)} аудио` : '',
    line.input_tokens || line.output_tokens
      ? `${formatTokens(line.input_tokens)} → ${formatTokens(line.output_tokens)} токенов`
      : '',
    pluralize(line.requests, ['запрос', 'запроса', 'запросов']),
    line.models.join(', '),
  ]
    .filter(Boolean)
    .join(' · ')
</script>
