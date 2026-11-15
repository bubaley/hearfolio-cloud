<template>
  <div class="flex w-full min-w-0 gap-2">
    <AppInput
      :model-value="value"
      readonly
      class="min-w-0 flex-1 font-mono"
      :aria-label="label"
      @focus="($event.target as HTMLInputElement | null)?.select()"
    />
    <AppButton
      variant="outline"
      :icon="copied ? Check : Copy"
      :label="copied ? 'Скопировано' : 'Копировать'"
      @click="copy"
    />
  </div>
</template>

<script setup lang="ts">
import { Check, Copy } from '@lucide/vue'

/** A value the admin pastes into the provider's console (redirect URI, sign-in link). */
const props = defineProps<{ value: string; label: string }>()
const toast = useToast()
const copied = ref(false)
watch(
  () => props.value,
  () => {
    copied.value = false
  },
)

const copy = async () => {
  try {
    await navigator.clipboard.writeText(props.value)
    copied.value = true
    toast.default('Скопировано')
  } catch {
    toast.error('Не удалось скопировать. Выделите адрес и скопируйте вручную')
  }
}
</script>
