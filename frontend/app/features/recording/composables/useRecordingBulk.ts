import { useQueryCache } from '@pinia/colada'
import { recordingsDestroy } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'
import type { ProjectBrief } from '~/features/project/resources/project'
import { pluralize } from '~/features/project/composables/projectLabels'
import type { Recording, TagBrief } from '../resources/recording'
import { recordingErrorMessage, recordingKeys, TRASH_DAYS, useRecordingMutations } from './useRecordingMutations'

type Target = Pick<Recording, 'id' | 'project' | 'visibility' | 'tags'>

/** Data type of a recordings drag from the list; sidebar projects accept it as a drop. */
export const RECORDING_DRAG_TYPE = 'application/x-hearfolio-recordings'
// What is being dragged right now (one tab, one drag at a time): the drop target needs project, visibility and tags.
const dragged = shallowRef<Target[]>([])

const recordingsLabel = (count: number) => pluralize(count, ['запись', 'записи', 'записей'])

/** Runs one request per recording (there is no bulk endpoint), a few at a time, and returns the failures. */
const each = async <T>(items: T[], task: (item: T) => Promise<unknown>) => {
  const failed: { item: T; error: unknown }[] = []
  const queue = [...items]
  const worker = async () => {
    for (let item = queue.shift(); item !== undefined; item = queue.shift()) {
      try {
        await task(item)
      } catch (error) {
        failed.push({ item, error })
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, items.length) }, worker))
  return failed
}

/**
 * Actions on one or many recordings that report once: moving into a project (the detail page, bulk bar, drag & drop
 * onto a sidebar project), adding or removing tags, deleting. Moves and deletions offer «Отменить».
 */
export const useRecordingBulk = () => {
  const client = useApiClient()
  const queryCache = useQueryCache()
  const toast = useToast()
  const mutations = useRecordingMutations()

  const setProject = (items: { id: string; project: ProjectBrief | null }[]) =>
    each(items, ({ id, project }) =>
      mutations.patch(id, { project_id: project?.id ?? null }, { project }, { quiet: true }),
    )

  const moveToProject = async (items: Target[], target: ProjectBrief | null) => {
    const changing = items.filter((item) => (item.project?.id ?? null) !== (target?.id ?? null))
    if (!changing.length) return
    const previous = changing.map((item) => ({ id: item.id, project: item.project }))
    const failed = await setProject(changing.map((item) => ({ id: item.id, project: target })))
    void queryCache.invalidateQueries({ key: recordingKeys.lists })
    if (failed.length === changing.length) {
      toast.error(recordingErrorMessage(failed[0]!.error, 'Не удалось перенести'))
      return
    }
    const moved = previous.filter((item) => !failed.some((failure) => failure.item.id === item.id))
    const count = moved.length
    const what = count === 1 && changing.length === 1 ? '' : ` ${recordingsLabel(count)}`
    // Shared recordings in a private project are seen by its members only; personal ones stay with the author.
    const shared = changing.some((item) => item.visibility === 'organization')
    const message = target
      ? `Перенесено${what} в «${target.name}»${target.is_private && shared ? ' · видят только участники проекта' : ''}`
      : `Убрано из проекта${what}`
    toast.default(message, {
      description: failed.length ? `Не удалось перенести: ${recordingsLabel(failed.length)}` : undefined,
      duration: 8000,
      action: {
        label: 'Отменить',
        onClick: () =>
          void setProject(moved).then((undoFailed) => {
            void queryCache.invalidateQueries({ key: recordingKeys.lists })
            if (undoFailed.length) toast.error('Не удалось вернуть проект')
          }),
      },
    })
  }

  /** Bulk tag edit: `added` go to every recording, `removed` leave every recording; other tags stay. */
  const changeTags = async (items: Target[], added: TagBrief[], removed: TagBrief[]) => {
    const removedIds = new Set(removed.map((tag) => tag.id))
    const failed = await each(items, (item) => {
      const tags = [
        ...item.tags.filter((tag) => !removedIds.has(tag.id)),
        ...added.filter((tag) => !item.tags.some((own) => own.id === tag.id)),
      ]
      return mutations.patch(item.id, { tag_ids: tags.map((tag) => tag.id) }, { tags }, { quiet: true })
    })
    void queryCache.invalidateQueries({ key: recordingKeys.lists })
    if (failed.length) toast.error(`Не удалось изменить теги: ${recordingsLabel(failed.length)}`)
  }

  const removeMany = async (items: Target[]) => {
    const failed = await each(items, (item) =>
      recordingsDestroy({ client, throwOnError: true, path: { item_id: item.id } }),
    )
    void queryCache.invalidateQueries({ key: recordingKeys.lists })
    const deleted = items.filter((item) => !failed.some((failure) => failure.item.id === item.id))
    if (!deleted.length) {
      toast.error(recordingErrorMessage(failed[0]?.error, 'Не удалось удалить'))
      return
    }
    toast.default(`В корзине: ${recordingsLabel(deleted.length)}`, {
      description: failed.length
        ? `Не удалось удалить: ${recordingsLabel(failed.length)}`
        : `Их можно восстановить в корзине в течение ${TRASH_DAYS} дней`,
      duration: 8000,
      action: { label: 'Отменить', onClick: () => void restoreMany(deleted.map((item) => item.id)) },
    })
  }

  const restoreMany = async (ids: string[]) => {
    const failed = await each(ids, (id) => mutations.restore(id))
    void queryCache.invalidateQueries({ key: recordingKeys.lists })
    if (failed.length) return
    if (ids.length === 1)
      toast.default('Запись восстановлена', {
        action: {
          label: 'Открыть',
          onClick: () => void navigateTo({ name: 'recordings-id', params: { id: ids[0]! } }),
        },
      })
    else toast.default(`Восстановлено: ${recordingsLabel(ids.length)}`)
  }

  const startDrag = (event: DragEvent, items: Target[]) => {
    dragged.value = items
    if (!event.dataTransfer) return
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData(RECORDING_DRAG_TYPE, JSON.stringify(items.map((item) => item.id)))
    event.dataTransfer.setData('text/plain', `${window.location.origin}/recordings/${items[0]?.id ?? ''}`)
  }
  /** A drop of dragged list rows onto a project (the sidebar). */
  const dropOnProject = async (project: ProjectBrief) => {
    const items = dragged.value
    dragged.value = []
    if (items.length) await moveToProject(items, project)
  }

  return { moveToProject, changeTags, removeMany, restoreMany, startDrag, dropOnProject }
}
