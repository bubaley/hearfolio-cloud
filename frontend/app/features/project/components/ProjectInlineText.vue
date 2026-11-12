<template>
  <textarea
    v-if="editable"
    ref="field"
    v-model="draft"
    rows="1"
    :maxlength="maxlength"
    :placeholder="placeholder"
    :aria-label="label"
    class="-mx-1 block w-full resize-none overflow-hidden rounded-md bg-transparent px-1 outline-none placeholder:text-muted-foreground/70 hover:bg-field-hover focus-visible:bg-field-hover focus-visible:ring-2 focus-visible:ring-ring/40"
    @input="resize"
    @keydown.enter="onEnter"
    @keydown.esc.prevent="cancel"
    @blur="commit"
  />
  <component
    :is="as"
    v-else-if="value"
    class="break-words whitespace-pre-line"
    >{{ value }}</component
  >
</template>

<script setup lang="ts">
import { useResizeObserver } from '@vueuse/core'

/**
 * Notion-like inline text: looks like plain text, edits in place. Enter (single line) or blur saves, Escape
 * restores. `required` keeps the old value when the field is emptied.
 */
const props = withDefaults(
  defineProps<{
    value: string
    editable: boolean
    label: string
    placeholder?: string
    multiline?: boolean
    required?: boolean
    maxlength?: number
    as?: string
  }>(),
  { as: 'p' },
)
const emit = defineEmits<{ save: [value: string] }>()

const field = ref<HTMLTextAreaElement>()
const draft = ref(props.value)
watch(
  () => props.value,
  (value) => {
    if (document.activeElement !== field.value) draft.value = value
    void nextTick(resize)
  },
)

function resize() {
  const element = field.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${element.scrollHeight}px`
}
onMounted(resize)
useResizeObserver(field, resize)

const normalize = (text: string) => (props.multiline ? text.trim() : text.replace(/\s+/g, ' ').trim())

function commit() {
  const next = normalize(draft.value)
  if (props.required && !next) {
    draft.value = props.value
    void nextTick(resize)
    return
  }
  draft.value = next
  if (next !== props.value) emit('save', next)
}

function cancel() {
  draft.value = props.value
  field.value?.blur()
}

// Single line: Enter saves. Multiline: Enter is a new line, ⌘/Ctrl+Enter saves.
function onEnter(event: KeyboardEvent) {
  if (props.multiline && !event.metaKey && !event.ctrlKey) return
  event.preventDefault()
  field.value?.blur()
}
</script>
