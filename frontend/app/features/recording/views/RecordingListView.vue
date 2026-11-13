<template>
  <AppPageView
    :title="screen.title"
    :description="screen.description"
    content-class="p-0"
  >
    <RecordingList
      :key="scope"
      :fixed="screen.fixed"
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
  </AppPageView>
</template>

<script setup lang="ts">
import { Sparkles, UserPlus } from '@lucide/vue'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'
import type { RecordingFilters } from '../resources/recording'
import { TRASH_DAYS } from '../composables/useRecordingMutations'
import RecordingList from '../components/list/RecordingList.vue'

const route = useRoute()
const setupStore = useSetupStore()
const { isAdmin } = useOrganizationRole()
const organizationName = computed(() => setupStore.state.organization?.name ?? '')

// One route, three screens: «Все записи», «Личные» (?personal=1) and «Корзина» (?deleted=1).
const scope = computed(() =>
  route.query.deleted === '1' ? 'trash' : route.query.personal === '1' ? 'personal' : 'all',
)
const screen = computed<{ title: string; description: string; fixed: RecordingFilters }>(() => {
  if (scope.value === 'trash')
    return {
      title: 'Корзина',
      description: `Удалённые записи можно восстановить в течение ${TRASH_DAYS} дней, потом они удаляются навсегда вместе с аудио`,
      fixed: { deleted: true },
    }
  if (scope.value === 'personal')
    return { title: 'Личные', description: 'Записи, которые видите только вы', fixed: { personal: true } }
  return { title: 'Все записи', description: `Записи организации «${organizationName.value}»`, fixed: {} }
})

useHead({ title: () => screen.value.title })
</script>
