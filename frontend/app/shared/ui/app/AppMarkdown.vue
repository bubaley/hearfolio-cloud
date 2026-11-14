<script setup lang="ts">
import { Square, SquareCheck } from '@lucide/vue'
import { h, type VNodeChild } from 'vue'
import AppIcon from './AppIcon.vue'
import { parseMarkdown, type MdBlock, type MdInline } from '~/shared/lib/markdown'

/**
 * Renders Markdown (AI summaries) as Vue nodes from `parseMarkdown`: no `v-html`, raw HTML in the source shows as
 * text, links open in a new tab and only http(s)/mailto are linked.
 */
/** `md`: reading text (a summary, a shared page); `sm`: dense places. */
const props = withDefaults(defineProps<{ source: string | null | undefined; size?: 'sm' | 'md' }>(), { size: 'sm' })

const blocks = computed(() => parseMarkdown(props.source))

const inline = (nodes: MdInline[]): VNodeChild[] =>
  nodes.map((node) => {
    switch (node.type) {
      case 'text':
        return node.text
      case 'br':
        return h('br')
      case 'strong':
        return h('strong', { class: 'font-semibold' }, inline(node.children))
      case 'em':
        return h('em', inline(node.children))
      case 'del':
        return h('del', { class: 'text-muted-foreground' }, inline(node.children))
      case 'code':
        return h('code', { class: 'rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]' }, node.text)
      case 'link':
        return h(
          'a',
          {
            href: node.href,
            target: '_blank',
            rel: 'noopener noreferrer nofollow',
            class: 'text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary',
          },
          inline(node.children),
        )
    }
  })

const HEADING_CLASS = {
  1: 'mt-6 text-xl font-semibold first:mt-0',
  2: 'mt-6 text-lg font-semibold first:mt-0',
  3: 'mt-5 text-base font-semibold first:mt-0',
  4: 'mt-4 font-semibold first:mt-0',
  5: 'mt-4 font-semibold first:mt-0',
  6: 'mt-4 font-semibold text-muted-foreground first:mt-0',
} as const

const ALIGN_CLASS = { left: 'text-left', center: 'text-center', right: 'text-right' } as const

const block = (node: MdBlock): VNodeChild => {
  switch (node.type) {
    case 'heading':
      return h(`h${node.level}`, { class: HEADING_CLASS[node.level] }, inline(node.children))
    case 'paragraph':
      return h('p', { class: 'mt-3 first:mt-0' }, inline(node.children))
    case 'hr':
      return h('hr', { class: 'my-5 border-border' })
    case 'code':
      return h(
        'pre',
        { class: 'mt-3 overflow-x-auto rounded-md bg-muted p-3 font-mono text-sm first:mt-0' },
        h('code', node.text),
      )
    case 'quote':
      return h(
        'blockquote',
        { class: 'mt-3 border-l-2 border-border-strong pl-3 text-muted-foreground first:mt-0' },
        node.children.map(block),
      )
    case 'list':
      return h(
        node.ordered ? 'ol' : 'ul',
        {
          class: ['mt-2 flex flex-col gap-1 pl-5 first:mt-0', node.ordered ? 'list-decimal' : 'list-disc'],
          start: node.ordered && node.start !== 1 ? node.start : undefined,
        },
        node.items.map((item, index) => {
          const checked = node.checked[index]
          if (checked === null || checked === undefined) return h('li', { class: 'pl-1 [&>p]:mt-0' }, item.map(block))
          // A task item: a read-only check mark instead of the bullet.
          return h('li', { class: '-ml-5 flex list-none items-start gap-2 [&>p]:mt-0' }, [
            h(AppIcon, {
              icon: checked ? SquareCheck : Square,
              size: 'sm',
              class: ['mt-0.5 shrink-0', checked ? 'text-primary' : 'text-muted-foreground'],
              label: checked ? 'Выполнено' : 'Не выполнено',
            }),
            h('div', { class: ['min-w-0 flex-1', checked && 'text-muted-foreground line-through'] }, item.map(block)),
          ])
        }),
      )
    case 'table':
      return h('div', { class: 'mt-3 overflow-x-auto first:mt-0' }, [
        h('table', { class: 'w-full border-collapse text-sm leading-relaxed' }, [
          h(
            'thead',
            h(
              'tr',
              node.header.map((cell, index) =>
                h(
                  'th',
                  {
                    class: [
                      'border-b border-border-strong px-2 py-1.5 text-left font-semibold',
                      ALIGN_CLASS[node.align[index] ?? 'left'],
                    ],
                  },
                  inline(cell),
                ),
              ),
            ),
          ),
          h(
            'tbody',
            node.rows.map((row) =>
              h(
                'tr',
                row.map((cell, index) =>
                  h(
                    'td',
                    {
                      class: ['border-b border-border px-2 py-1.5 align-top', ALIGN_CLASS[node.align[index] ?? 'left']],
                    },
                    inline(cell),
                  ),
                ),
              ),
            ),
          ),
        ]),
      ])
  }
}

const render = () =>
  h(
    'div',
    { class: ['break-words', props.size === 'md' ? 'text-[0.9375rem] leading-7' : 'text-sm leading-relaxed'] },
    blocks.value.map(block),
  )
</script>

<template>
  <component :is="render" />
</template>
