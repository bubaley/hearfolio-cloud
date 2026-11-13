import type { InjectionKey } from 'vue'

/**
 * A layout provides the width every AppPage under it is centered in (header, controls and body share it), so header
 * actions sit at the edge of the content instead of drifting to the far right of a wide screen. Example: settings.
 */
export const PAGE_CONTAINER_CLASS: InjectionKey<string> = Symbol('page-container-class')
