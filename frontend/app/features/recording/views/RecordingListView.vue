<template>
  <AppPageView
    :title="personal ? 'Личные' : 'Все записи'"
    :description="personal ? 'Записи, которые видите только вы' : `Записи организации «${organizationName}»`"
    content-class="p-0"
  >
    <RecordingList
      :key="personal ? 'personal' : 'all'"
      :fixed="personal ? { personal: true } : {}"
    >
      <template
        v-if="isAdmin && !personal"
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
import RecordingList from '../components/list/RecordingList.vue'

const route = useRoute()
const setupStore = useSetupStore()
const { isAdmin } = useOrganizationRole()
const personal = computed(() => route.query.personal === '1')
const organizationName = computed(() => setupStore.state.organization?.name ?? '')
</script>
