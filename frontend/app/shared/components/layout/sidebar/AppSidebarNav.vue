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
        class="group/section flex h-8 items-center gap-1 pr-1 pl-2"
      >
        <span class="min-w-0 flex-1 truncate text-xs font-medium text-muted-foreground">{{ section.title }}</span>
        <AppButton
          v-if="section.action"
          variant="ghost"
          size="icon-xs"
          text-variant="muted"
          :icon="section.action.icon"
          :aria-label="section.action.label"
          :title="section.action.label"
          @click="section.action.onClick"
        />
      </div>
      <AppSidebarLink
        v-for="(item, index) in section.items"
        :key="index"
        :item="item"
        :active="activeKey === `${sectionIndex}:${index}`"
      />
      <p
        v-if="!section.items.length && section.empty"
        class="px-2 py-1.5 text-xs text-muted-foreground"
      >
        {{ section.empty }}
      </p>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import AppSidebarLink from './AppSidebarLink.vue'
import type { SidebarSection } from './types'

const props = defineProps<{ sections: SidebarSection[] }>()

const route = useRoute()
const router = useRouter()

const sameRoute = (name: string, current: string) => current === name || current.startsWith(`${name}-`)

// One active item: the route name matches (or is nested under it) and the item's own query matches; the item with
// the most matching query keys wins, so «Личные» (?personal=1) beats «Все записи» on the same route.
const activeKey = computed(() => {
  const current = route.name?.toString() ?? ''
  let best: { key: string; score: number } | null = null
  props.sections.forEach((section, sectionIndex) =>
    section.items.forEach((item, index) => {
      const target = router.resolve(item.to)
      const name = target.name?.toString()
      if (!name || !sameRoute(name, current)) return
      const keys = Object.keys(target.query)
      if (keys.some((key) => String(route.query[key] ?? '') !== String(target.query[key] ?? ''))) return
      const extra = Object.keys(route.query).filter((key) => !keys.includes(key)).length
      const score = keys.length * 10 - extra + name.length / 1000
      if (!best || score > best.score) best = { key: `${sectionIndex}:${index}`, score }
    }),
  )
  return (best as { key: string } | null)?.key ?? null
})
</script>
