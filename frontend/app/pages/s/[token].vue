<template><PublicShareView :token="String(route.params.token)" /></template>
<script setup lang="ts">
import PublicShareView from '~/features/share/views/PublicShareView.vue'

// Public and rendered on the server: guests open shared links without an account and without the app chrome.
definePageMeta({ layout: false, auth: false })
const route = useRoute()
</script>
