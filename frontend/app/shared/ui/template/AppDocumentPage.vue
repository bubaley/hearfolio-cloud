<template>
  <AppPageView content-class="px-4 pb-16 md:px-10">
    <!-- Loading, not found and similar states replace the whole document. -->
    <slot
      v-if="$slots.state"
      name="state"
    />
    <article
      v-else
      class="mx-auto flex w-full max-w-5xl flex-col gap-8 pt-8 md:pt-14"
    >
      <header class="flex flex-col gap-3">
        <div class="flex items-start justify-between gap-2">
          <slot name="icon">
            <span
              v-if="icon"
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
          <slot name="actions" />
        </div>
        <h1 class="text-3xl leading-tight font-bold tracking-tight">
          <slot name="title">{{ title }}</slot>
        </h1>
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
  </AppPageView>
</template>

<script setup lang="ts">
import type { Component } from 'vue'
import AppIcon from '../app/AppIcon.vue'
import AppPageView from '../app/AppPageView.vue'

/**
 * A Notion-like document page: a large icon (with actions on the right), a big title, badges, a description, then
 * the content in one centered column. The project page and the recording screens («Все записи», «Личные»,
 * «Корзина») share it. A list inside it pulls itself to the column edges (`-mx-3 md:-mx-4`).
 */
defineProps<{ title?: string; description?: string; icon?: Component }>()
</script>
