<template>
  <div class="flex flex-col gap-2">
    <AppInput
      v-if="candidates.length > 6 || search"
      v-model="search"
      is-search
      clearable
      size="sm"
      placeholder="Найти по имени или email"
      aria-label="Поиск участников организации"
    />
    <div
      v-if="isLoading && !items.length"
      class="flex flex-col gap-2 py-1"
      aria-label="Загрузка"
    >
      <AppSkeleton
        v-for="row in 3"
        :key="row"
        class="h-8"
      />
    </div>
    <AppAlert
      v-else-if="error && !items.length"
      tone="destructive"
      title="Не удалось загрузить участников"
    >
      <AppTextButton
        label="Повторить"
        weight="medium"
        @click="refetch()"
      />
    </AppAlert>
    <ul
      v-else-if="visible.length"
      class="flex max-h-64 flex-col overflow-y-auto"
    >
      <li
        v-for="member in visible"
        :key="member.user_id"
      >
        <label
          class="flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 hover:bg-row-hover md:min-h-10"
        >
          <AppCheckbox
            v-model="model"
            :val="member.user_id"
            :aria-label="userDisplayName(member.user)"
          />
          <AppAvatar
            :name="userDisplayName(member.user)"
            size="small"
            variant="soft"
          />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm">{{ userDisplayName(member.user) }}</span>
            <span
              v-if="userDisplayName(member.user) !== member.user.email"
              class="block truncate text-xs text-muted-foreground"
              >{{ member.user.email }}</span
            >
          </span>
        </label>
      </li>
    </ul>
    <p
      v-else
      class="px-2 py-3 text-sm text-muted-foreground"
    >
      {{ search ? 'Никого не нашли' : emptyText }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { useResourceList } from '~/shared/api/useResource'
import { organizationUserResource } from '~/features/organization/resources/organizationUser'
import { userDisplayName } from '../resources/project'

/** Checklist of organization members (user ids in `v-model`), minus `excludeIds` (the caller, current members). */
const props = withDefaults(defineProps<{ excludeIds?: string[]; emptyText?: string }>(), {
  excludeIds: () => [],
  emptyText: 'Больше некого добавить',
})
const model = defineModel<string[]>({ default: () => [] })

const setupStore = useSetupStore()
const organizationId = computed(() => setupStore.state.organization?.id ?? null)
const { items, isLoading, error, refetch } = useResourceList(organizationUserResource, {
  params: () => ({ organization_id: organizationId.value }),
  pageSize: 200,
  enabled: () => Boolean(organizationId.value),
})

const search = ref('')
const candidates = computed(() => items.value.filter((member) => !props.excludeIds.includes(member.user_id)))
const visible = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return candidates.value
  return candidates.value.filter((member) =>
    [member.user.email, member.user.first_name, member.user.last_name].join(' ').toLowerCase().includes(query),
  )
})
</script>
