<template>
  <main class="flex min-h-dvh flex-col items-center bg-background px-4 py-10 sm:justify-center sm:py-12">
    <div class="flex w-full max-w-md flex-col gap-6">
      <AppLogo class="mx-auto w-fit" />
      <div class="rounded-xl border border-border bg-card p-5 sm:p-7">
        <slot />
      </div>
      <p
        v-if="$slots.footer"
        class="text-center text-sm text-muted-foreground"
      >
        <slot name="footer" />
      </p>
    </div>
  </main>
</template>

<script setup lang="ts">
import AppLogo from './header/AppLogo.vue'
</script>
