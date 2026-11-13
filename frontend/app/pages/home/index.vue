<template><div /></template>
<script setup lang="ts">
// The workspace home is the recordings list; `/home` stays the post-login target (and keeps `?personal=1`).
definePageMeta({ redirect: (to) => ({ name: 'recordings', query: to.query }) })
</script>
