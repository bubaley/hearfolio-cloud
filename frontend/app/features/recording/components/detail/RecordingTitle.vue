<template>
  <!-- The heading is named by the title itself; the field inside keeps its own label for editing. -->
  <h1
    class="m-0"
    :aria-label="title.trim() || placeholder"
  >
    <textarea
      id="recording-title"
      ref="field"
      v-model="draft"
      aria-label="Название записи"
      rows="1"
      maxlength="255"
      spellcheck="false"
      :placeholder="placeholder"
      class="block w-full resize-none overflow-hidden rounded-md bg-transparent px-1 py-0.5 text-2xl leading-tight font-bold tracking-tight break-words outline-none placeholder:text-muted-foreground/60 hover:bg-field-hover focus:bg-transparent focus-visible:ring-0 md:-mx-1 md:text-[2rem]"
      @keydown.enter.prevent="field?.blur()"
      @keydown.esc.prevent="cancel"
      @blur="commit"
      @input="resize"
    />
  </h1>
</template>

<script setup lang="ts">
import { useResizeObserver } from '@vueuse/core'

/** Notion-like title: click and type; Enter or leaving the field saves, Escape restores. */
const props = defineProps<{ title: string; placeholder: string }>()
const emit = defineEmits<{ save: [title: string] }>()

const field = ref<HTMLTextAreaElement>()
const draft = ref(props.title)

watch(
  () => props.title,
  (value) => {
    if (document.activeElement !== field.value) draft.value = value
    void nextTick(resize)
  },
)

const resize = () => {
  const el = field.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}
useResizeObserver(field, resize)
onMounted(resize)

const commit = () => {
  const value = draft.value.replace(/\s+/g, ' ').trim()
  if (!value) {
    draft.value = props.title
    void nextTick(resize)
    return
  }
  draft.value = value
  if (value !== props.title) emit('save', value)
}

const cancel = () => {
  draft.value = props.title
  void nextTick(() => {
    resize()
    field.value?.blur()
  })
}
</script>
