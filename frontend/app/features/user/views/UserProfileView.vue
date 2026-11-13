<template>
  <AppPageView
    title="Профиль"
    description="Ваше имя видят коллеги в записях, проектах и списке участников"
    content-class="px-4 pb-10"
  >
    <div class="flex flex-col gap-10 pt-4">
      <div class="flex min-w-0 items-center gap-4">
        <AppAvatar
          :name="displayName"
          size="large"
          variant="soft"
        />
        <div class="min-w-0">
          <div class="truncate text-lg font-semibold">{{ displayName }}</div>
          <div
            v-if="displayName !== user?.email"
            class="truncate text-sm text-muted-foreground"
          >
            {{ user?.email }}
          </div>
        </div>
      </div>

      <AppSection
        title="Учётная запись"
        title-size="md"
        class="gap-1"
      >
        <form @submit.prevent="saveState.execute">
          <AppSettingRow
            label="Имя"
            for-id="profile-first-name"
          >
            <AppInput
              id="profile-first-name"
              v-model="firstName"
              class="w-full sm:w-64"
              autocomplete="given-name"
              maxlength="150"
            />
          </AppSettingRow>
          <AppSettingRow
            label="Фамилия"
            for-id="profile-last-name"
          >
            <AppInput
              id="profile-last-name"
              v-model="lastName"
              class="w-full sm:w-64"
              autocomplete="family-name"
              maxlength="150"
            />
          </AppSettingRow>
          <AppSettingRow
            label="Электронная почта"
            description="Для входа. Изменить её может администратор сервера"
          >
            <span class="text-sm break-all">{{ user?.email }}</span>
          </AppSettingRow>
          <div
            v-if="dirty"
            class="flex justify-end gap-2 pt-3"
          >
            <AppButton
              variant="secondary"
              label="Отменить"
              @click="reset"
            />
            <AppButton
              type="submit"
              label="Сохранить"
              :loading="saveState.loading.value"
            />
          </div>
        </form>
      </AppSection>

      <AppSection
        v-if="userId"
        title="Безопасность"
        title-size="md"
        class="gap-1"
      >
        <AppSettingRow
          label="Пароль"
          description="После смены пароля другие устройства выйдут из аккаунта"
        >
          <UserChangePasswordButton :user-id="userId" />
        </AppSettingRow>
        <AppSettingRow
          label="Сеансы"
          description="Завершить вход в браузерах и приложениях, включая этот"
        >
          <AppButton
            variant="outline"
            label="Выйти на всех устройствах"
            :loading="logoutAllState.loading.value"
            @click="logoutAllState.execute"
          />
        </AppSettingRow>
      </AppSection>

      <UserTokensSection
        v-if="userId"
        :user-id="userId"
      />
    </div>
  </AppPageView>
</template>

<script setup lang="ts">
import { useQueryCache } from '@pinia/colada'
import UserChangePasswordButton from '~/features/user/components/UserChangePasswordButton.vue'
import UserTokensSection from '~/features/user/components/UserTokensSection.vue'
import { usersPartialUpdate } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'
import { SESSION_KEY } from '~/shared/composables/useSession'

const { user, logoutAll } = useSession()
const client = useApiClient()
const queryCache = useQueryCache()
const toast = useToast()

const userId = computed(() => user.value?.id ?? null)
const displayName = computed(() => userDisplayName(user.value) || 'Профиль')

const firstName = ref('')
const lastName = ref('')
const reset = () => {
  firstName.value = user.value?.first_name ?? ''
  lastName.value = user.value?.last_name ?? ''
}
watch(() => [user.value?.first_name, user.value?.last_name], reset, { immediate: true })
const dirty = computed(
  () =>
    firstName.value.trim() !== (user.value?.first_name ?? '') ||
    lastName.value.trim() !== (user.value?.last_name ?? ''),
)

const saveState = useActionState(
  async () => {
    if (!userId.value) return
    try {
      await usersPartialUpdate({
        client,
        throwOnError: true,
        path: { item_id: userId.value },
        body: { first_name: firstName.value.trim(), last_name: lastName.value.trim() },
      })
    } catch (error) {
      toast.error('Не удалось сохранить имя')
      throw error
    }
    // The sidebar, member lists and the profile all read the name from the session.
    await queryCache.invalidateQueries({ key: [...SESSION_KEY] })
  },
  { successNotification: 'Сохранено' },
)

// Ends every session of the user (all devices), then signs out here too.
const logoutAllState = useActionState(() => logoutAll.mutateAsync(), {
  errorNotification: 'Не удалось завершить сеансы. Попробуйте ещё раз',
})
</script>
