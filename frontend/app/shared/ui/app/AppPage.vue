<script setup lang="ts">
import { inject } from 'vue'
import { Separator } from '~/shared/ui/shadcn/separator'
import { PAGE_CONTAINER_CLASS, PAGE_GUTTER_CLASS, PAGE_TITLE_CLASS, PAGE_TOP_CLASS } from './pageContainer'

export type AppPageProps = { title?: string; contentClass?: string }

withDefaults(defineProps<AppPageProps>(), { title: '', contentClass: 'p-4' })

const containerClass = inject(PAGE_CONTAINER_CLASS, '')
const container = containerClass ? ['mx-auto w-full', containerClass] : undefined
// Inside a container (settings) the page is one scrolling document, like the workspace pages: the header scrolls
// with the content (no divider), the controls stick to the top, and everything shares one gutter.
const gutter = PAGE_GUTTER_CLASS
</script>

<template>
  <section class="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden">
    <template v-if="container">
      <div
        data-slot="page-body"
        class="min-h-0 flex-1 overflow-auto"
      >
        <div
          v-if="title || $slots.header"
          :class="[gutter, PAGE_TOP_CLASS]"
        >
          <div :class="[container, title && 'flex items-start gap-3']">
            <h1
              v-if="title"
              class="m-0 min-w-0 flex-1"
              :class="PAGE_TITLE_CLASS"
            >
              {{ title }}
            </h1>
            <slot name="header" />
          </div>
        </div>
        <div
          v-if="$slots.subheader"
          :class="[gutter, 'pt-3']"
        >
          <div :class="container">
            <slot name="subheader" />
          </div>
        </div>
        <div
          v-if="$slots.controls"
          class="sticky top-0 z-10 bg-background pt-4"
          :class="gutter"
        >
          <div :class="container">
            <slot name="controls" />
          </div>
        </div>
        <div :class="[gutter, $slots.controls ? 'pt-2' : 'pt-6', 'pb-16']">
          <div :class="container">
            <slot />
          </div>
        </div>
      </div>
      <footer
        v-if="$slots.footer"
        class="shrink-0 border-t border-border py-4"
        :class="gutter"
      >
        <div :class="container">
          <slot name="footer" />
        </div>
      </footer>
    </template>
    <template v-else>
      <div
        v-if="title || $slots.header"
        class="shrink-0"
      >
        <div :class="[title && 'flex min-h-[40px] items-center gap-3 px-3']">
          <h1
            v-if="title"
            class="m-0 min-w-0 flex-1 text-lg font-semibold tracking-tight"
          >
            {{ title }}
          </h1>
          <slot name="header" />
        </div>
      </div>
      <div
        v-if="$slots.subheader"
        class="shrink-0 px-3"
      >
        <slot name="subheader" />
      </div>
      <Separator v-if="title || $slots.header || $slots.subheader" />
      <div
        v-if="$slots.controls"
        class="shrink-0 px-3"
      >
        <slot name="controls" />
      </div>
      <div
        data-slot="page-body"
        class="min-h-0 flex-1 overflow-auto"
      >
        <div
          class="h-full min-h-full"
          :class="contentClass"
        >
          <slot />
        </div>
      </div>
      <footer
        v-if="$slots.footer"
        class="shrink-0 border-t border-border p-4"
      >
        <slot name="footer" />
      </footer>
    </template>
  </section>
</template>
