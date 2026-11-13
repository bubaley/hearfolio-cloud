<script setup lang="ts">
import { computed, useAttrs, useSlots, type Component, type HTMLAttributes } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { Button } from '~/shared/ui/shadcn/button'
import { appControlIconSize, type AppButtonSize } from './types/control'
import {
  appButtonExtraClasses,
  appButtonPrimitiveSize,
  resolveAppButtonSize,
  type AppButtonTextVariant,
  type AppButtonVariant,
} from './appButton'

export type AppButtonProps = {
  onClick?: (event: MouseEvent) => void
  to?: RouteLocationRaw
  label?: string
  variant?: AppButtonVariant
  size?: AppButtonSize
  textVariant?: AppButtonTextVariant
  /** A Lucide component. Icon-only buttons must have `aria-label` (or `title`). */
  icon?: Component
  iconClass?: HTMLAttributes['class']
  iconPosition?: 'start' | 'end'
  loading?: boolean
  disabled?: boolean
  fluid?: boolean
  type?: 'button' | 'submit' | 'reset'
  /** Renders a real link (`<a href>`) styled as a button: external pages, downloads, public pages. */
  href?: string
  /** With `href`: opens it in a new tab (`rel="noopener noreferrer"`). */
  external?: boolean
}

const props = withDefaults(defineProps<AppButtonProps>(), {
  variant: 'default',
  textVariant: 'base',
  size: 'md',
  iconPosition: 'start',
  type: 'button',
})
const router = useRouter()
const slots = useSlots()
const attrs = useAttrs()
const emit = defineEmits<{ click: [event: MouseEvent] }>()
const iconOnly = computed(() => Boolean(props.icon) && !props.label && !slots.default)
const controlSize = computed(() => resolveAppButtonSize(props.size, iconOnly.value))
if (import.meta.dev && iconOnly.value && !attrs['aria-label'] && !attrs['aria-labelledby'] && !attrs.title) {
  console.warn('[AppButton] Icon-only buttons need an accessible name: pass `aria-label` or `title`.')
}
function handleClick(event: MouseEvent) {
  emit('click', event)
  if (props.to) void router.push(props.to)
}
</script>

<template>
  <Button
    v-if="href"
    as="a"
    :href="href"
    :target="external ? '_blank' : undefined"
    :rel="external ? 'noopener noreferrer' : undefined"
    :variant="variant"
    :size="appButtonPrimitiveSize(controlSize)"
    :class="appButtonExtraClasses({ variant, textVariant, fluid })"
    @click="emit('click', $event)"
  >
    <AppIcon
      v-if="icon && iconPosition === 'start'"
      :size="appControlIconSize[controlSize]"
      :icon="icon"
      :class="iconClass"
    />
    <slot>{{ label }}</slot>
    <AppIcon
      v-if="icon && iconPosition === 'end'"
      :size="appControlIconSize[controlSize]"
      :icon="icon"
      :class="iconClass"
    />
  </Button>
  <Button
    v-else
    :type="type"
    :variant="variant"
    :size="appButtonPrimitiveSize(controlSize)"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
    :class="appButtonExtraClasses({ variant, textVariant, fluid })"
    @click="handleClick"
  >
    <AppIcon
      v-if="loading"
      :size="appControlIconSize[controlSize]"
      loading
      :class="iconClass"
    />
    <AppIcon
      v-else-if="icon && iconPosition === 'start'"
      :size="appControlIconSize[controlSize]"
      :icon="icon"
      :class="iconClass"
    />
    <slot>{{ label }}</slot>
    <AppIcon
      v-if="icon && iconPosition === 'end' && !loading"
      :size="appControlIconSize[controlSize]"
      :icon="icon"
      :class="iconClass"
    />
  </Button>
</template>
