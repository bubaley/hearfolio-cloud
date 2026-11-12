<template>
  <AppPageView
    :title="personal ? 'Личные' : 'Все записи'"
    :description="personal ? 'Записи, которые видите только вы' : `Записи организации «${organizationName}»`"
    content-class="px-4 pb-10"
  >
    <div class="flex min-h-[50vh] items-center justify-center">
      <div class="max-w-sm">
        <AppResultState
          :icon="personal ? Lock : AudioLines"
          :title="personal ? 'Личных записей пока нет' : 'Здесь появятся записи'"
          description="Запишите встречу или звонок в приложении Hearfolio и выберите эту организацию — расшифровка и саммари появятся здесь через минуту после остановки"
        >
          <template
            v-if="isAdmin"
            #actions
          >
            <AppButton
              variant="outline"
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
        </AppResultState>
      </div>
    </div>
  </AppPageView>
</template>

<script setup lang="ts">
import { AudioLines, Lock, Sparkles, UserPlus } from '@lucide/vue'
import { useOrganizationRole } from '~/features/organization/composables/useOrganizationRole'

// Placeholder workspace home until the recording screens exist; the sidebar's «Все записи» and «Личные» land here.
const route = useRoute()
const setupStore = useSetupStore()
const { isAdmin } = useOrganizationRole()
const personal = computed(() => route.query.personal === '1')
const organizationName = computed(() => setupStore.state.organization?.name ?? '')
</script>
