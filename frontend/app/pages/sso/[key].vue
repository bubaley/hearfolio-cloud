<template><SsoLoginView /></template>
<script setup lang="ts">
import SsoLoginView from '~/features/sso/views/SsoLoginView.vue'

// Public and client-only (routeRules): the organization's sign-in through its provider, `/sso/<key>`.
definePageMeta({ layout: 'auth', auth: false })
useSeoMeta({ title: 'Вход через SSO', robots: 'noindex' })
</script>
