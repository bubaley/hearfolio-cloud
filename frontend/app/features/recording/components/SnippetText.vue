<template>
  <span
    ><template
      v-for="(part, index) in parts"
      :key="index"
      ><mark
        v-if="part.highlight"
        class="rounded-sm bg-tag-yellow px-0.5 text-tag-yellow-foreground"
        >{{ part.text }}</mark
      ><template v-else>{{ part.text }}</template></template
    ></span
  >
</template>

<script setup lang="ts">
import type { SnippetPart } from '../resources/recording'

// The API splits the fragment into plain and matching parts; nothing here is parsed as HTML.
defineProps<{ parts: SnippetPart[] }>()
</script>
