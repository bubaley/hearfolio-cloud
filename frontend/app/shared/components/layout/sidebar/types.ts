import type { Component } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

export type SidebarItem = {
  to: RouteLocationRaw
  label: string
  icon?: Component
  /** Short muted text on the right (a count, «скоро»). */
  hint?: string
}

export type SidebarSection = {
  /** Small muted heading; a section without one is a plain group of items. */
  title?: string
  items: SidebarItem[]
  /** Icon button next to the heading («+» for a new project). */
  action?: { label: string; icon: Component; onClick: () => void }
  /** Shown instead of items when the section is empty. */
  empty?: string
}
