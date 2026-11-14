<template>
  <div class="flex h-full min-h-0 w-full min-w-0 flex-col">
    <!-- Top bar, Notion-like: the whole width of the main area, where the page is on the left and its actions on the
         right. It does not scroll, so «Поделиться», «Загрузить» and «⋯» stay at hand in a long transcript. -->
    <div
      data-slot="page-topbar"
      class="flex h-12 shrink-0 items-center justify-between gap-2 px-1 md:h-11 md:px-3"
    >
      <nav
        class="flex min-w-0 items-center gap-1 text-sm text-muted-foreground"
        aria-label="Где вы"
      >
        <!-- With the sidebar hidden this bar is the only one (AppLayout drops its own), so it brings the sidebar back. -->
        <AppButton
          v-if="collapsed"
          variant="ghost"
          size="icon"
          text-variant="muted"
          class="hidden shrink-0 md:inline-flex"
          :icon="PanelLeftOpen"
          aria-label="Показать боковую панель"
          @click="collapsed = false"
        />
        <slot name="lead">
          <span
            v-if="title"
            class="flex min-w-0 items-center gap-2 px-3 md:px-2"
          >
            <AppIcon
              v-if="icon"
              :icon="icon"
              size="sm"
              class="shrink-0"
            />
            <span class="truncate">{{ title }}</span>
          </span>
        </slot>
      </nav>
      <div
        v-if="$slots.actions"
        :class="[PAGE_ACTIONS_CLASS, 'flex-nowrap']"
      >
        <slot name="actions" />
      </div>
    </div>
    <div
      ref="scroller"
      data-slot="page-body"
      tabindex="-1"
      class="min-h-0 flex-1 overflow-y-auto pb-16 outline-none"
      :class="PAGE_GUTTER_CLASS"
    >
      <!-- Loading, not found and similar states replace the whole document, in the same column. -->
      <div
        v-if="$slots.state"
        class="mx-auto w-full max-w-(--page-width)"
        :class="DOCUMENT_TOP_CLASS"
      >
        <slot name="state" />
      </div>
      <article
        v-else
        class="mx-auto flex w-full max-w-(--page-width) flex-col gap-6"
        :class="DOCUMENT_TOP_CLASS"
      >
        <header class="flex flex-col gap-3">
          <!-- The large icon of a list or a project; a recording has none and starts with its title. -->
          <div
            v-if="icon || $slots.icon"
            class="flex h-14 items-center"
          >
            <slot name="icon">
              <span
                class="inline-flex size-14 shrink-0 items-center justify-center"
                aria-hidden="true"
              >
                <AppIcon
                  :icon="icon"
                  :size="44"
                  class="text-muted-foreground"
                />
              </span>
            </slot>
          </div>
          <slot name="heading">
            <h1 :class="PAGE_TITLE_CLASS">
              <slot name="title">{{ title }}</slot>
            </h1>
          </slot>
          <div
            v-if="$slots.meta"
            class="flex flex-wrap items-center gap-2"
          >
            <slot name="meta" />
          </div>
          <div
            v-if="description || $slots.description"
            class="text-base text-muted-foreground"
          >
            <slot name="description">{{ description }}</slot>
          </div>
        </header>
        <slot />
      </article>
    </div>
    <!-- Fixed under the scrolling document (the audio player). -->
    <slot name="footer" />
  </div>
</template>

<script setup lang="ts">
import { PanelLeftOpen } from '@lucide/vue'
import type { Component } from 'vue'
import AppIcon from '../app/AppIcon.vue'
import { PAGE_ACTIONS_CLASS, PAGE_GUTTER_CLASS, PAGE_TITLE_CLASS } from '../app/pageContainer'

// The top bar already separates the document from the window edge: a smaller top offset than on settings pages.
const DOCUMENT_TOP_CLASS = 'pt-4 md:pt-6'

/**
 * The page of the workspace: a top bar over the whole main area (`#lead`: where you are or the way back, by default
 * the icon and the title; `#actions` on the right), then one centered column with an optional large icon, a big
 * title, badges, a description and the content. «Все записи», «Личные», «Корзина», the project page and the
 * recording page share it. A list inside it pulls itself to the column edges (`-mx-3 md:-mx-4`).
 */
defineProps<{ title?: string; description?: string; icon?: Component }>()

const { collapsed } = useSidebar()
const scroller = ref<HTMLElement>()
defineExpose({ scroller })
</script>
