<template>
  <AppHeaderProfileButton
    align="start"
    side="top"
  >
    <template #trigger>
      <button
        type="button"
        class="flex h-11 w-full min-w-0 items-center gap-2.5 rounded-md px-2 text-left text-sm text-sidebar-foreground/80 transition-colors outline-none hover:bg-sidebar-accent/70 focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-sidebar-accent md:h-9"
        aria-label="Меню профиля"
      >
        <AppAvatar
          :name="displayName"
          size="small"
          variant="soft"
        />
        <span class="min-w-0 flex-1 truncate">{{ displayName }}</span>
        <AppIcon
          :icon="ChevronsUpDown"
          size="xs"
          tone="muted"
        />
      </button>
    </template>
  </AppHeaderProfileButton>
</template>

<script setup lang="ts">
import { ChevronsUpDown } from '@lucide/vue'
import AppHeaderProfileButton from '../header/AppHeaderProfileButton.vue'

const { user } = useSession()
const displayName = computed(() => {
  const name = [user.value?.first_name, user.value?.last_name].filter(Boolean).join(' ').trim()
  return name || user.value?.email || 'Профиль'
})
</script>
