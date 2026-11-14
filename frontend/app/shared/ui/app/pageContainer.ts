import type { InjectionKey } from 'vue'

/**
 * A layout provides the width every AppPage under it is centered in (header, controls and body share it), so header
 * actions sit at the edge of the content instead of drifting to the far right of a wide screen. Example: settings.
 */
export const PAGE_CONTAINER_CLASS: InjectionKey<string> = Symbol('page-container-class')

/**
 * One page shell for every screen (docs/ui-audit.md): the same side gutter, top offset and h1, so a title starts at
 * the same point on «Все записи», a project, a recording and any settings page.
 */
export const PAGE_GUTTER_CLASS = 'px-4 md:px-10'
export const PAGE_TOP_CLASS = 'pt-6 md:pt-10'
export const PAGE_TITLE_CLASS = 'text-2xl leading-tight font-bold tracking-tight md:text-3xl'
/** Header actions: one row at the top right of the content column; 44px touch targets on phones. */
export const PAGE_ACTIONS_CLASS =
  'flex shrink-0 flex-wrap items-center justify-end gap-2 max-md:[&_[data-slot=button]]:min-h-11 max-md:[&_[data-slot=button]]:min-w-11'
