import { AudioLines, Lock } from '@lucide/vue'
import type { SidebarItem } from '~/shared/components/layout/sidebar/types'

// Main sidebar of the workspace. Recording screens replace `home` with their own routes; «Проекты» are listed below
// these entries by the default layout.
export const workspaceNavigation: SidebarItem[] = [
  { to: { name: 'home' }, label: 'Все записи', icon: AudioLines },
  { to: { name: 'home', query: { personal: '1' } }, label: 'Личные', icon: Lock },
]
