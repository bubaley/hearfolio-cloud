<template><ProjectView :id="String(route.params.id)" /></template>
<script setup lang="ts">
import ProjectView from '~/features/project/views/ProjectView.vue'

const route = useRoute()
</script>
