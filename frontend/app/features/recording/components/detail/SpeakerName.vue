<template>
  <span
    v-if="!editable"
    class="text-xs leading-7 font-medium"
    :class="toneClass"
    >{{ name }}</span
  >
  <AppPopover
    v-else
    v-model:open="open"
    label="Имя спикера"
    content-class="w-72 p-3"
  >
    <template #trigger>
      <!-- Inside a clickable row: the click renames, it does not seek. -->
      <button
        type="button"
        class="-mx-1 w-fit rounded px-1 text-left text-xs leading-7 font-medium outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
        :class="toneClass"
        :title="`Переименовать «${name}»`"
        @click.stop
      >
        {{ name }}
      </button>
    </template>
    <form
      class="flex flex-col gap-3"
      @submit.prevent="save"
      @click.stop
    >
      <AppInput
        v-model="draft"
        label="Имя спикера"
        :placeholder="fallback"
        maxlength="60"
        autocomplete="off"
        autofocus
      />
      <p class="text-xs text-muted-foreground">Имя поменяется во всей расшифровке, при копировании и выгрузке.</p>
      <div class="flex justify-end gap-2">
        <AppButton
          v-if="custom"
          type="button"
          variant="ghost"
          text-variant="muted"
          size="sm"
          :label="`Вернуть «${fallback}»`"
          @click="reset"
        />
        <AppButton
          type="submit"
          size="sm"
          label="Сохранить"
        />
      </div>
    </form>
  </AppPopover>
</template>

<script setup lang="ts">
/**
 * A speaker's name above a transcript paragraph. When `editable`, a click opens a small form: the new name applies to
 * every paragraph of this speaker; an empty name (or «Вернуть») goes back to «Спикер N».
 */
const props = defineProps<{
  /** Shown name: the stored one or «Спикер N». */
  name: string
  /** «Спикер N» for this label. */
  fallback: string
  toneClass?: string
  editable?: boolean
}>()
const emit = defineEmits<{ rename: [name: string | null] }>()

const open = ref(false)
const draft = ref('')
const custom = computed(() => props.name !== props.fallback)
watch(open, (value) => {
  if (value) draft.value = custom.value ? props.name : ''
})

const save = () => {
  const name = draft.value.split(/\s+/).filter(Boolean).join(' ')
  if (name !== (custom.value ? props.name : '')) emit('rename', name || null)
  open.value = false
}
const reset = () => {
  emit('rename', null)
  open.value = false
}
</script>
