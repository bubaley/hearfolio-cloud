<script setup lang="ts">
import { inject } from 'vue'
import { PAGE_CONTAINER_CLASS } from '../app/pageContainer'

withDefaults(
  defineProps<{ title?: string; titleSize?: TitleSizeToken; description?: string; backAction?: () => void }>(),
  { titleSize: 'xl' },
)
// Inside a layout container AppPage already pads around it; a second gutter would shift the title off the content.
const inContainer = Boolean(inject(PAGE_CONTAINER_CLASS, ''))
</script>
<template>
  <header
    class="flex min-h-12 w-full flex-wrap items-center gap-3 py-3"
    :class="inContainer ? 'px-0' : 'px-4'"
  >
    <AppBackButton
      v-if="backAction"
      :back-action="backAction"
    />
    <slot name="prefix" />
    <div
      v-if="title || description || $slots.title || $slots['title-append']"
      class="min-w-[min(100%,14rem)] flex-1 basis-56"
    >
      <div class="flex min-w-0 flex-wrap items-center gap-2">
        <AppTitle
          v-if="title || $slots.title"
          as="h1"
          :size="titleSize"
        >
          <slot name="title">{{ title }}</slot> </AppTitle
        ><slot name="title-append" />
      </div>
      <p
        v-if="description"
        class="mt-0.5 text-sm text-muted-foreground"
      >
        {{ description }}
      </p>
    </div>
    <!-- Phones: every header button is a 44px touch target. -->
    <div
      v-if="$slots.actions"
      class="ml-auto flex max-w-full flex-wrap items-center justify-end gap-2 max-md:[&_[data-slot=button]]:min-h-11 max-md:[&_[data-slot=button]]:min-w-11"
    >
      <slot name="actions" />
    </div>
  </header>
</template>
