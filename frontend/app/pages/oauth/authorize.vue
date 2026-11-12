<template><OAuthConsentView /></template>
<script setup lang="ts">
import OAuthConsentView from '~/features/oauth/views/OAuthConsentView.vue'

// Needs a session (the guard returns here after /auth) but no selected organization.
definePageMeta({ layout: 'auth', organization: false })
useSeoMeta({ title: 'Подключение приложения', robots: 'noindex' })
</script>
