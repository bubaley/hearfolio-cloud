<script setup lang="ts">
import { inject } from 'vue'
import { Separator } from '~/shared/ui/shadcn/separator'
import { PAGE_CONTAINER_CLASS } from './pageContainer'

export type AppPageProps = { title?: string; contentClass?: string }

withDefaults(defineProps<AppPageProps>(), { title: '', contentClass: 'p-4' })

const containerClass = inject(PAGE_CONTAINER_CLASS, '')
const container = containerClass ? ['mx-auto w-full', containerClass] : undefined
</script>

<template>
  <section class="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden">
    <div
      v-if="title || $slots.header"
      class="shrink-0"
    >
      <div :class="[container, title && 'flex min-h-[40px] items-center gap-3 px-3']">
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
      <div :class="container">
        <slot name="subheader" />
      </div>
    </div>
    <Separator v-if="title || $slots.header || $slots.subheader" />
    <div
      v-if="$slots.controls"
      class="shrink-0 px-3"
    >
      <div :class="container">
        <slot name="controls" />
      </div>
    </div>
    <div
      data-slot="page-body"
      class="min-h-0 flex-1 overflow-auto"
    >
      <div
        class="h-full min-h-full"
        :class="contentClass"
      >
        <div
          v-if="container"
          :class="[container, 'min-h-full']"
        >
          <slot />
        </div>
        <slot v-else />
      </div>
    </div>
    <footer
      v-if="$slots.footer"
      class="shrink-0 border-t border-border p-4"
    >
      <div :class="container">
        <slot name="footer" />
      </div>
    </footer>
  </section>
</template>
