import type { Component, InjectionKey } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

/** True inside the phone sheet: items drop keyboard hints such as ⌘K. */
export const SIDEBAR_IN_SHEET: InjectionKey<boolean> = Symbol('sidebar-in-sheet')

export type SidebarItem = {
  /** Route of a link item; an item without one is a button and needs `onClick` («Поиск»). */
  to?: RouteLocationRaw
  onClick?: () => void
  label: string
  icon?: Component
  /** Shown instead of `icon` (project emoji). */
  emoji?: string
  /** Short muted text on the right (a count, «скоро»). */
  hint?: string
  /** Small muted icon on the right (lock of a private project); `trailingLabel` names it for screen readers. */
  trailingIcon?: Component
  trailingLabel?: string
}

export type SidebarSection = {
  /** Small muted heading; a section without one is a plain group of items. */
  title?: string
  items: SidebarItem[]
  /** Icon button next to the heading («+» for a new project). */
  action?: { label: string; icon: Component; onClick: () => void }
  /** Shown instead of items when the section is empty. */
  empty?: string
  /** Skeleton rows instead of the empty text while the items load. */
  loading?: boolean
  /** The heading folds the section; the state is remembered under this id. */
  collapsibleId?: string
  /** Show this many items and «Показать все» for the rest (the active item always stays visible). */
  limit?: number
}
