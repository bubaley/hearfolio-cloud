import { AudioLines, Lock } from '@lucide/vue'
import type { SidebarItem } from '~/shared/components/layout/sidebar/types'

// Main sidebar of the workspace; «Поиск» (a dialog, not a route) and «Проекты» are added by the default layout.
export const workspaceNavigation: SidebarItem[] = [
  { to: { name: 'recordings' }, label: 'Все записи', icon: AudioLines },
  { to: { name: 'recordings', query: { personal: '1' } }, label: 'Личные', icon: Lock },
]
