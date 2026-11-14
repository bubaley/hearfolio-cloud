<template>
  <AppDocumentPage
    :title="screen.title"
    :description="screen.description"
    :icon="screen.icon"
  >
    <template
      v-if="scope !== 'trash'"
      #actions
    >
      <AppButton
        variant="ghost"
        :icon="Upload"
        label="Загрузить"
        text-variant="muted"
        @click="list?.pickFiles()"
      />
    </template>
    <!-- The list brings its own gutters (sticky toolbar, row hover); pull it to the column edges. -->
    <RecordingList
      ref="list"
      :key="scope"
      :fixed="screen.fixed"
      class="-mx-3 md:-mx-4"
    >
      <template
        v-if="isAdmin && scope === 'all'"
        #empty-actions
      >
        <AppButton
          variant="ghost"
          text-variant="muted"
          label="Настроить AI и модели"
          :icon="Sparkles"
          :to="{ name: 'settings-ai' }"
        />
        <AppButton
          variant="ghost"
          text-variant="muted"
          label="Пригласить коллег"
          :icon="UserPlus"
          :to="{ name: 'settings-invites' }"
        />
      </template>
    </RecordingList>
  </AppDocumentPage>
</template>

<script setup lang="ts">
import type { Component } from 'vue'
import { AudioLines, Lock, Sparkles, Trash2, Upload, UserPlus } from '@lucide/vue'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import type { RecordingFilters } from '../resources/recording'
import { daysLabel, useTrashDays } from '../composables/useRecordingMutations'
import RecordingList from '../components/list/RecordingList.vue'

const route = useRoute()
const list = ref<{ pickFiles: () => void }>()
const setupStore = useSetupStore()
const { isAdmin } = useOrganizationRole()
const trashDays = useTrashDays()
const organizationName = computed(() => setupStore.state.organization?.name ?? '')

// One route, three screens: «Все записи», «Личные» (?personal=1) and «Корзина» (?deleted=1).
const scope = computed(() =>
  route.query.deleted === '1' ? 'trash' : route.query.personal === '1' ? 'personal' : 'all',
)
const screen = computed<{ title: string; description: string; icon: Component; fixed: RecordingFilters }>(() => {
  if (scope.value === 'trash')
    return {
      title: 'Корзина',
      description: `Удалённые записи можно восстановить в течение ${daysLabel(trashDays.value)}, потом они удаляются навсегда вместе с аудио`,
      icon: Trash2,
      fixed: { deleted: true },
    }
  if (scope.value === 'personal')
    return { title: 'Личные', description: 'Записи, которые видите только вы', icon: Lock, fixed: { personal: true } }
  return {
    title: 'Все записи',
    description: `Записи организации «${organizationName.value}»`,
    icon: AudioLines,
    fixed: {},
  }
})

useHead({ title: () => screen.value.title })
</script>
