<template>
  <!-- The page gutter sits outside the column, as in AppDocumentPage: the controls line up with the content. -->
  <div
    class="border-t border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80"
    :class="PAGE_GUTTER_CLASS"
    role="region"
    aria-label="Плеер"
  >
    <div
      class="mx-auto flex w-full max-w-(--page-width) flex-col gap-1 pt-1.5 pb-[max(0.5rem,env(safe-area-inset-bottom))] md:flex-row md:items-center md:gap-3 md:py-2"
    >
      <!-- Scrubber: the progress bar shows position, a transparent range input on top takes pointer and keys. -->
      <div class="group relative flex h-6 min-w-0 items-center md:order-2 md:flex-1">
        <AppProgress
          :value="percent"
          class="h-1 transition-[height] group-hover:h-1.5"
          aria-label="Позиция воспроизведения"
        />
        <input
          type="range"
          min="0"
          :max="Math.max(1, Math.round(player.durationMs.value))"
          step="1000"
          :value="Math.round(player.currentMs.value)"
          :disabled="disabled"
          :aria-valuetext="`${formatClock(player.currentMs.value)} из ${formatClock(player.durationMs.value)}`"
          aria-label="Перемотка"
          class="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
          @input="onScrub"
        />
      </div>
      <div class="flex items-center gap-1 md:contents">
        <span
          class="w-16 shrink-0 text-xs text-muted-foreground tabular-nums md:order-1 md:w-auto md:min-w-10 md:text-right"
          >{{ formatClock(player.currentMs.value) }}</span
        >
        <div class="flex flex-1 items-center justify-center gap-1 md:order-0 md:flex-none">
          <AppButton
            variant="ghost"
            size="icon"
            text-variant="muted"
            class="size-11 md:size-control-md"
            :icon="RotateCcw"
            aria-label="Назад на 15 секунд"
            title="Назад на 15 секунд"
            :disabled="disabled"
            @click="player.skip(-15_000)"
          />
          <AppButton
            variant="default"
            size="icon"
            class="size-11 rounded-full md:size-control-md"
            :icon="player.playing.value ? Pause : Play"
            :loading="player.loading.value && player.playing.value"
            :aria-label="player.playing.value ? 'Пауза' : 'Воспроизвести'"
            :title="player.playing.value ? 'Пауза (пробел)' : 'Воспроизвести (пробел)'"
            :disabled="disabled"
            @click="player.toggle()"
          />
          <AppButton
            variant="ghost"
            size="icon"
            text-variant="muted"
            class="size-11 md:size-control-md"
            :icon="RotateCw"
            aria-label="Вперёд на 15 секунд"
            title="Вперёд на 15 секунд"
            :disabled="disabled"
            @click="player.skip(15_000)"
          />
        </div>
        <span
          class="w-16 shrink-0 text-right text-xs text-muted-foreground tabular-nums md:order-3 md:w-auto md:min-w-10"
          >{{ formatClock(player.durationMs.value) }}</span
        >
        <AppButton
          variant="ghost"
          size="sm"
          text-variant="muted"
          class="h-11 w-14 shrink-0 tabular-nums md:order-4 md:h-control-sm md:w-12"
          :label="`${String(player.rate.value).replace('.', ',')}×`"
          :aria-label="`Скорость ${String(player.rate.value).replace('.', ',')}×, сменить`"
          title="Скорость воспроизведения"
          @click="player.cycleRate()"
        />
        <AppTooltip side="top">
          <template #trigger>
            <span
              class="hidden size-control-sm shrink-0 items-center justify-center text-muted-foreground md:order-5 md:inline-flex"
              tabindex="0"
              aria-label="Клавиши: пробел — пауза, стрелки влево и вправо — на 5 секунд"
            >
              <AppIcon
                :icon="Keyboard"
                size="sm"
              />
            </span>
          </template>
          <span class="flex flex-col gap-0.5 text-xs">
            <span>Пробел — пауза и воспроизведение</span>
            <span>← / → — на 5 секунд назад и вперёд</span>
          </span>
        </AppTooltip>
      </div>
    </div>
    <div
      v-if="player.failed.value"
      role="alert"
      class="flex items-center justify-center gap-2 pb-2 text-xs text-destructive"
    >
      <AppIcon
        :icon="CircleAlert"
        size="xs"
      />
      <span>Аудио недоступно</span>
      <AppTextButton
        label="Повторить"
        weight="medium"
        class="text-xs"
        @click="player.reload()"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { CircleAlert, Keyboard, Pause, Play, RotateCcw, RotateCw } from '@lucide/vue'
import type { AudioPlayer } from '../../composables/useAudioPlayer'
import { PAGE_GUTTER_CLASS } from '~/shared/ui/app/pageContainer'

const props = defineProps<{ player: AudioPlayer; disabled?: boolean }>()

const percent = computed(() =>
  props.player.durationMs.value ? (props.player.currentMs.value / props.player.durationMs.value) * 100 : 0,
)

const onScrub = (event: Event) => void props.player.seek(Number((event.target as HTMLInputElement).value))
</script>
