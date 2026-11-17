<template>
  <AppPageView
    title="Расходы на AI"
    description="Сколько стоили расшифровки и саммари — по данным провайдера, в долларах"
  >
    <div class="flex flex-col gap-6">
      <AppAlert
        v-if="!isAdmin"
        tone="info"
        title="Только для владельцев и администраторов"
        description="Расходы организации видят администраторы"
      />
      <template v-else>
        <div class="flex flex-wrap items-center gap-3">
          <AppSelect
            v-model="periodKey"
            :options="periodOptions"
            option-label="label"
            option-value="value"
            emit-value
            class="w-full sm:w-60"
            aria-label="Период"
          />
          <span class="text-sm text-muted-foreground">{{ periodLabel }}</span>
        </div>

        <AppAlert
          v-if="query.error.value"
          tone="destructive"
          title="Не удалось загрузить расходы"
        >
          <AppTextButton
            label="Повторить"
            weight="medium"
            @click="query.refetch()"
          />
        </AppAlert>

        <AppSkeleton
          v-else-if="!report"
          :lines="4"
        />

        <template v-else>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div
              v-for="tile in tiles"
              :key="tile.label"
              class="rounded-lg border border-border px-4 py-3"
            >
              <div class="text-xs text-muted-foreground">{{ tile.label }}</div>
              <div class="mt-1 text-xl font-semibold tabular-nums">{{ tile.value }}</div>
            </div>
          </div>

          <p
            v-if="!report.users.length"
            class="text-sm text-muted-foreground"
          >
            За этот период расходов нет.
          </p>
          <div
            v-else
            class="overflow-x-auto rounded-lg border border-border"
          >
            <table class="w-full min-w-[40rem] text-sm">
              <thead class="bg-muted/50 text-xs text-muted-foreground">
                <tr>
                  <th class="px-3 py-2 text-left font-medium">Пользователь</th>
                  <th class="px-3 py-2 text-right font-medium">Записей</th>
                  <th class="px-3 py-2 text-right font-medium">Аудио</th>
                  <th class="px-3 py-2 text-right font-medium">Расшифровка</th>
                  <th class="px-3 py-2 text-right font-medium">Саммари</th>
                  <th class="px-3 py-2 text-right font-medium">Прочее</th>
                  <th class="px-3 py-2 text-right font-medium">Итого</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in [...report.users, report.total]"
                  :key="row === report.total ? 'total' : (row.user_id ?? 'deleted')"
                  class="border-t border-border tabular-nums"
                  :class="row === report.total && 'bg-muted/50 font-medium'"
                >
                  <td class="px-3 py-2 text-left">{{ row.name }}</td>
                  <td class="px-3 py-2 text-right">{{ row.recordings }}</td>
                  <td class="px-3 py-2 text-right whitespace-nowrap">
                    {{ row.audio_ms ? formatAudio(row.audio_ms) : '—' }}
                  </td>
                  <td class="px-3 py-2 text-right">{{ formatUsd(row.transcription_cost_usd) }}</td>
                  <td class="px-3 py-2 text-right">{{ formatUsd(row.summary_cost_usd) }}</td>
                  <td class="px-3 py-2 text-right">{{ formatUsd(row.other_cost_usd) }}</td>
                  <td class="px-3 py-2 text-right font-semibold">{{ formatUsd(row.cost_usd) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <p class="text-xs text-muted-foreground">
            Автоматическая обработка записи — расход её автора, саммари, запущенное вручную, — расход того, кто его
            запустил. «Прочее» — названия, теги и имена спикеров.
            <template v-if="report.total.unknown_cost_requests">
              {{ pluralize(report.total.unknown_cost_requests, ['запрос', 'запроса', 'запросов']) }} без стоимости от
              провайдера — их нет в суммах.
            </template>
            <template v-if="report.accounting_since">
              Учёт ведётся с {{ formatDate(report.accounting_since, { format: 'D MMMM YYYY' }) }}.
            </template>
          </p>
        </template>
      </template>
    </div>
  </AppPageView>
</template>

<script setup lang="ts">
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import { pluralize } from '~/features/project/composables/projectLabels'
import { useOrganizationAiUsage } from '../composables/useAiUsage'
import { formatAudio, formatTokens, formatUsd } from '../utils/usageFormat'

const { isAdmin } = useOrganizationRole()
const { formatDate } = useDate()

type PeriodKey = 'month' | 'previous-month' | '7d' | '30d' | 'year'
const periodOptions: { value: PeriodKey; label: string }[] = [
  { value: 'month', label: 'Этот месяц' },
  { value: 'previous-month', label: 'Прошлый месяц' },
  { value: '7d', label: 'Последние 7 дней' },
  { value: '30d', label: 'Последние 30 дней' },
  { value: 'year', label: 'Этот год' },
]
const periodKey = ref<PeriodKey>('month')

// Local calendar boundaries; `until` is exclusive.
const period = computed(() => {
  const now = new Date()
  const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const tomorrow = new Date(startOfDay(now).getTime() + 86_400_000)
  switch (periodKey.value) {
    case 'previous-month':
      return {
        since: new Date(now.getFullYear(), now.getMonth() - 1, 1),
        until: new Date(now.getFullYear(), now.getMonth(), 1),
      }
    case '7d':
      return { since: new Date(tomorrow.getTime() - 7 * 86_400_000), until: tomorrow }
    case '30d':
      return { since: new Date(tomorrow.getTime() - 30 * 86_400_000), until: tomorrow }
    case 'year':
      return { since: new Date(now.getFullYear(), 0, 1), until: tomorrow }
    default:
      return { since: new Date(now.getFullYear(), now.getMonth(), 1), until: tomorrow }
  }
})
const periodLabel = computed(() => {
  const last = new Date(period.value.until.getTime() - 1)
  const since = formatDate(period.value.since.toISOString(), { format: 'D MMMM' })
  return `${since} — ${formatDate(last.toISOString(), { format: 'D MMMM YYYY' })}`
})

const query = useOrganizationAiUsage(period, () => isAdmin.value)
const report = computed(() => query.data.value)

const tiles = computed(() => {
  const total = report.value?.total
  if (!total) return []
  return [
    { label: 'Всего', value: formatUsd(total.cost_usd) },
    { label: 'Расшифровка', value: formatUsd(total.transcription_cost_usd) },
    { label: 'Саммари', value: formatUsd(total.summary_cost_usd) },
    { label: 'Токены', value: formatTokens(total.input_tokens + total.output_tokens) },
  ]
})
</script>
