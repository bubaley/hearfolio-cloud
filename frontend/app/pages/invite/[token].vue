<template><InviteAcceptView /></template>
<script setup lang="ts">
import InviteAcceptView from '~/features/organization/views/InviteAcceptView.vue'

// Public and client-only (routeRules): every preview counts against the per-IP invite limit, so it must come from
// the visitor, not from the Nuxt server.
definePageMeta({ layout: 'auth', auth: false })
useSeoMeta({ title: 'Приглашение', robots: 'noindex' })
</script>
