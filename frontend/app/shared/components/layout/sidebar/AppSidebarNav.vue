<template>
  <nav
    aria-label="Основная навигация"
    class="flex flex-col gap-4"
  >
    <div
      v-for="(section, sectionIndex) in sections"
      :key="section.title || sectionIndex"
      class="flex flex-col gap-px"
    >
      <div
        v-if="section.title"
        class="group/section flex h-11 items-center gap-1 pr-1 pl-2 md:h-8"
      >
        <button
          v-if="section.collapsibleId"
          type="button"
          class="flex min-w-0 flex-1 items-center gap-1 rounded-sm text-left text-xs font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          :aria-expanded="!isFolded(section)"
          @click="toggleFold(section)"
        >
          <span class="truncate">{{ section.title }}</span>
          <AppIcon
            :icon="ChevronRight"
            size="xs"
            class="shrink-0 transition-transform"
            :class="!isFolded(section) && 'rotate-90'"
          />
        </button>
        <span
          v-else
          class="min-w-0 flex-1 truncate text-xs font-medium text-muted-foreground"
          >{{ section.title }}</span
        >
        <AppButton
          v-if="section.action"
          variant="ghost"
          size="icon-xs"
          text-variant="muted"
          class="size-11 md:size-control-xs"
          :icon="section.action.icon"
          :aria-label="section.action.label"
          :title="section.action.label"
          @click="section.action.onClick"
        />
      </div>
      <template v-if="!isFolded(section)">
        <AppSidebarLink
          v-for="{ item, index } in visibleItems(section, sectionIndex)"
          :key="index"
          :item="item"
          :active="activeKey === `${sectionIndex}:${index}`"
        />
        <button
          v-if="hiddenCount(section, sectionIndex) || expanded[sectionKey(section, sectionIndex)]"
          type="button"
          class="flex h-11 items-center gap-2.5 rounded-md px-2 text-left text-xs text-muted-foreground outline-none hover:bg-sidebar-accent/70 hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-ring md:h-8"
          @click="toggleExpanded(section, sectionIndex)"
        >
          {{
            expanded[sectionKey(section, sectionIndex)]
              ? 'Свернуть'
              : `Показать ещё ${hiddenCount(section, sectionIndex)}`
          }}
        </button>
        <div
          v-if="section.loading && !section.items.length"
          aria-label="Загрузка"
          class="flex flex-col gap-2 px-2 py-1.5"
        >
          <AppSkeleton
            v-for="row in 3"
            :key="row"
            class="h-4"
          />
        </div>
        <p
          v-else-if="!section.items.length && section.empty"
          class="px-2 py-1.5 text-xs text-muted-foreground"
        >
          {{ section.empty }}
        </p>
      </template>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { ChevronRight } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import AppSidebarLink from './AppSidebarLink.vue'
import type { SidebarSection } from './types'

const props = defineProps<{ sections: SidebarSection[] }>()

const route = useRoute()
const router = useRouter()

const sameRoute = (name: string, current: string) => current === name || current.startsWith(`${name}-`)

// One active item: the route name matches (or is nested under it), the item's own params and query match; the item
// with the most matching query keys wins, so «Личные» (?personal=1) beats «Все записи» on the same route.
const activeKey = computed(() => {
  const current = route.name?.toString() ?? ''
  let best: { key: string; score: number } | null = null
  props.sections.forEach((section, sectionIndex) =>
    section.items.forEach((item, index) => {
      if (!item.to) return
      const target = router.resolve(item.to)
      const name = target.name?.toString()
      if (!name || !sameRoute(name, current)) return
      if (Object.entries(target.params).some(([key, value]) => String(route.params[key] ?? '') !== String(value)))
        return
      const keys = Object.keys(target.query)
      if (keys.some((key) => String(route.query[key] ?? '') !== String(target.query[key] ?? ''))) return
      const extra = Object.keys(route.query).filter((key) => !keys.includes(key)).length
      const score = keys.length * 10 - extra + name.length / 1000
      if (!best || score > best.score) best = { key: `${sectionIndex}:${index}`, score }
    }),
  )
  return (best as { key: string } | null)?.key ?? null
})

// Folded sections are remembered per browser; «Показать все» is per visit.
const folded = useCookie<string[]>('sidebar-folded', {
  default: () => [],
  maxAge: 60 * 60 * 24 * 365,
  sameSite: 'lax',
})
const isFolded = (section: SidebarSection) =>
  Boolean(section.collapsibleId && folded.value.includes(section.collapsibleId))
const toggleFold = (section: SidebarSection) => {
  const id = section.collapsibleId
  if (!id) return
  folded.value = folded.value.includes(id) ? folded.value.filter((value) => value !== id) : [...folded.value, id]
}

const expanded = ref<Record<string, boolean>>({})
const sectionKey = (section: SidebarSection, sectionIndex: number) => section.collapsibleId ?? String(sectionIndex)
const toggleExpanded = (section: SidebarSection, sectionIndex: number) => {
  const key = sectionKey(section, sectionIndex)
  expanded.value = { ...expanded.value, [key]: !expanded.value[key] }
}

const visibleItems = (section: SidebarSection, sectionIndex: number) => {
  const all = section.items.map((item, index) => ({ item, index }))
  if (!section.limit || expanded.value[sectionKey(section, sectionIndex)] || all.length <= section.limit + 1) return all
  const active = activeKey.value?.startsWith(`${sectionIndex}:`) ? Number(activeKey.value.split(':')[1]) : -1
  return all.filter(({ index }) => index < section.limit! || index === active)
}
const hiddenCount = (section: SidebarSection, sectionIndex: number) =>
  section.items.length - visibleItems(section, sectionIndex).length
</script>
