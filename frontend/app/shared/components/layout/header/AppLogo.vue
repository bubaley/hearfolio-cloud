<template>
  <div class="flex items-center text-foreground">
    <!-- The Hearfolio mark, as in the desktop app: a sound wave on a rounded square that inverts with the theme. -->
    <span
      class="grid size-[26px] shrink-0 place-items-center rounded-[7px] bg-foreground text-background"
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        class="size-[17px]"
      >
        <path d="M3 10v4m4-7v10m5-14v18m5-14v10m4-7v4" />
      </svg>
    </span>
    <div class="ml-2 text-sm font-semibold sm:text-lg">{{ name }}</div>
  </div>
</template>

<script setup lang="ts">
const { name } = useAppConfig()
</script>
