<template>
  <AppMenu
    title="Учётная запись"
    :actions="actions"
    :align="align"
    :side="side"
  >
    <template #trigger>
      <slot name="trigger">
        <AppButton
          variant="ghost"
          size="icon"
          :icon="User"
          aria-label="Меню профиля"
        />
      </slot>
    </template>
    <div class="border-t border-border px-2 pt-3 pb-2">
      <div class="mb-2 text-xs text-muted-foreground">Оформление</div>
      <AppThemeSwitcher />
    </div>
  </AppMenu>
</template>
<script setup lang="ts">
import { LogOut, Settings, User } from '@lucide/vue'
import type { AppMenuAction } from '~/shared/ui/app/AppMenu.vue'

withDefaults(defineProps<{ align?: 'start' | 'center' | 'end'; side?: 'top' | 'right' | 'bottom' | 'left' }>(), {
  align: 'end',
  side: 'bottom',
})

const { logout } = useSession()
const actions: AppMenuAction[] = [
  {
    label: 'Профиль',
    icon: User,
    action: async () => {
      await navigateTo({ name: 'settings-profile' })
    },
  },
  {
    label: 'Настройки',
    icon: Settings,
    action: async () => {
      await navigateTo({ name: 'settings' })
    },
  },
  {
    label: 'Выйти',
    separatorBefore: true,
    icon: LogOut,
    action: async () => {
      try {
        await logout.mutateAsync()
      } catch {
        useToast().error('Не удалось выйти. Попробуйте ещё раз')
      }
    },
  },
]
</script>
