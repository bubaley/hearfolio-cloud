import { AudioLines, Lock, Trash2 } from '@lucide/vue'
import type { SidebarItem } from '~/shared/components/layout/sidebar/types'

// Main sidebar of the workspace; «Поиск» (a dialog, not a route) and «Проекты» are added by the default layout.
export const workspaceNavigation: SidebarItem[] = [
  { to: { name: 'recordings' }, label: 'Все записи', icon: AudioLines },
  { to: { name: 'recordings', query: { personal: '1' } }, label: 'Личные', icon: Lock },
]

// Below «Проекты», at the bottom of the workspace navigation.
export const workspaceFooterNavigation: SidebarItem[] = [
  { to: { name: 'recordings', query: { deleted: '1' } }, label: 'Корзина', icon: Trash2 },
]
