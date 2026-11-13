import { Building, Building2, FileText, Folder, Mail, Sparkles, Tags, User, Users, UsersRound } from '@lucide/vue'
import type { Component } from 'vue'

export type SettingsNavigationSection = 'organization' | 'account' | 'instance'

export type SettingsNavigationItem = {
  to: { name: string }
  label: string
  icon: Component
  /** Sidebar group; entries without one belong to the selected organization. */
  section?: SettingsNavigationSection
  /** Only org owners/admins (and superusers) see it. */
  adminOnly?: boolean
  superuserOnly?: boolean
}

export const settingsSections: { key: SettingsNavigationSection; title: string }[] = [
  { key: 'organization', title: 'Организация' },
  { key: 'account', title: 'Учётная запись' },
  { key: 'instance', title: 'Сервер' },
]

// Settings sidebar, in display order. `make new-domain` inserts its entry above the marker line.
export const settingsNavigation: SettingsNavigationItem[] = [
  { to: { name: 'settings-organization' }, label: 'Общие', icon: Building2 },
  { to: { name: 'settings-members' }, label: 'Участники', icon: UsersRound },
  { to: { name: 'settings-invites' }, label: 'Приглашения', icon: Mail, adminOnly: true },
  { to: { name: 'settings-ai' }, label: 'AI и модели', icon: Sparkles, adminOnly: true },
  { to: { name: 'settings-projects' }, label: 'Проекты', icon: Folder },
  { to: { name: 'settings-tags' }, label: 'Теги', icon: Tags },
  { to: { name: 'settings-summary-templates' }, label: 'Шаблоны саммари', icon: FileText },
  { to: { name: 'settings-profile' }, label: 'Профиль', icon: User, section: 'account' },
  { to: { name: 'settings-organizations' }, label: 'Организации', icon: Building, section: 'account' },
  { to: { name: 'settings-users' }, label: 'Пользователи', icon: Users, section: 'instance', superuserOnly: true },
  // new-domain: entries above this line
]
