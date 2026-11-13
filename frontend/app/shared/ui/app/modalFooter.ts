import type { InjectionKey } from 'vue'

/**
 * Provided by the AppModal footer. Actions rendered there follow the one dialog pattern: stacked full-width with the
 * primary on top on phones, right-aligned buttons of natural width from `sm` up.
 */
export const IN_MODAL_FOOTER: InjectionKey<boolean> = Symbol('in-modal-footer')
