import { useQueryCache } from '@pinia/colada'
import { recordingsBulk, type RecordingBulkResultSchema, type RecordingBulkSchema } from '~/shared/api/generated'
import { useApiClient } from '~/shared/api/useResource'
import type { ProjectBrief } from '~/features/project/resources/project'
import { pluralize } from '~/features/project/composables/projectLabels'
import type { Recording, RecordingDetail, TagBrief } from '../resources/recording'
import { daysLabel, recordingErrorMessage, recordingKeys, useTrashDays } from './useRecordingMutations'

type Target = Pick<Recording, 'id' | 'project' | 'visibility' | 'tags'>
type BulkResult = RecordingBulkResultSchema

/** Data type of a recordings drag from the list; sidebar projects accept it as a drop. */
export const RECORDING_DRAG_TYPE = 'application/x-hearfolio-recordings'
// What is being dragged right now (one tab, one drag at a time): the drop target needs project, visibility and tags.
const dragged = shallowRef<Target[]>([])

// `POST /recordings/bulk` takes up to 200 ids per call.
const BULK_LIMIT = 200

const recordingsLabel = (count: number) => pluralize(count, ['запись', 'записи', 'записей'])

/**
 * Actions on one or many recordings through `POST /recordings/bulk`, reported once: moving into a project (the detail
 * page, bulk bar, drag & drop onto a sidebar project), adding or removing tags, deleting and restoring. The server
 * applies each recording's own permissions and reports what it skipped. Moves and deletions offer «Отменить», which
 * sends the inverse bulk call.
 */
export const useRecordingBulk = () => {
  const client = useApiClient()
  const queryCache = useQueryCache()
  const toast = useToast()
  const trashDays = useTrashDays()

  const send = async (body: Omit<RecordingBulkSchema, 'ids'>, ids: string[]): Promise<BulkResult> => {
    const result: BulkResult = { updated: [], skipped: [] }
    for (let start = 0; start < ids.length; start += BULK_LIMIT) {
      const { data } = await recordingsBulk({
        client,
        throwOnError: true,
        body: { ...body, ids: ids.slice(start, start + BULK_LIMIT) },
      })
      result.updated.push(...data.updated)
      result.skipped.push(...data.skipped)
    }
    return result
  }

  // Events arrive by realtime too; refetching here makes the screen right without waiting for them.
  const refresh = (ids: string[]) => {
    void queryCache.invalidateQueries({ key: recordingKeys.lists })
    for (const id of ids) void queryCache.invalidateQueries({ key: recordingKeys.detail(id) })
  }

  /** Show `changes` on the open recordings right away; returns how to put them back. */
  const optimistic = (ids: string[], changes: Partial<RecordingDetail>) => {
    const previous = new Map<string, RecordingDetail>()
    for (const id of ids) {
      const current = queryCache.getQueryData(recordingKeys.detail(id)) as RecordingDetail | undefined
      if (!current) continue
      previous.set(id, current)
      queryCache.setQueryData(recordingKeys.detail(id), { ...current, ...changes })
    }
    return (only?: string[]) => {
      for (const [id, item] of previous)
        if (!only || only.includes(id)) queryCache.setQueryData(recordingKeys.detail(id), item)
    }
  }

  /** Moves recordings into `target` (null: out of their project); undo moves each back to where it was. */
  const moveToProject = async (items: Target[], target: ProjectBrief | null) => {
    const changing = items.filter((item) => (item.project?.id ?? null) !== (target?.id ?? null))
    if (!changing.length) return
    const ids = changing.map((item) => item.id)
    const revert = optimistic(ids, { project_id: target?.id ?? null, project: target })
    let result: BulkResult
    try {
      result = await send({ action: 'move', project_id: target?.id ?? null }, ids)
    } catch (error) {
      revert()
      refresh(ids)
      toast.error(recordingErrorMessage(error, 'Не удалось перенести'))
      return
    }
    refresh(ids)
    const moved = changing.filter((item) => result.updated.includes(item.id))
    revert(result.skipped.map((item) => item.id))
    if (!moved.length) {
      toast.error('Не удалось перенести: записи недоступны')
      return
    }
    const count = moved.length
    const what = count === 1 && changing.length === 1 ? '' : ` ${recordingsLabel(count)}`
    // Shared recordings in a private project are seen by its members only; personal ones stay with the author.
    const shared = moved.some((item) => item.visibility === 'organization')
    const message = target
      ? `Перенесено${what} в «${target.name}»${target.is_private && shared ? ' · видят только участники проекта' : ''}`
      : `Убрано из проекта${what}`
    toast.default(message, {
      description: result.skipped.length
        ? `Не удалось перенести: ${recordingsLabel(result.skipped.length)}`
        : undefined,
      duration: 8000,
      action: { label: 'Отменить', onClick: () => void moveBack(moved) },
    })
  }

  /** The inverse of a move: one bulk call per original project. */
  const moveBack = async (items: Target[]) => {
    const byProject = new Map<string | null, string[]>()
    for (const item of items) {
      const key = item.project?.id ?? null
      byProject.set(key, [...(byProject.get(key) ?? []), item.id])
    }
    const ids = items.map((item) => item.id)
    try {
      const results = await Promise.all(
        [...byProject].map(([projectId, group]) => send({ action: 'move', project_id: projectId }, group)),
      )
      if (results.some((result) => result.skipped.length)) toast.error('Не удалось вернуть проект у части записей')
    } catch {
      toast.error('Не удалось вернуть проект')
    } finally {
      refresh(ids)
    }
  }

  /** Bulk tag edit: `added` go to every recording, `removed` leave every recording; other tags stay. */
  const changeTags = async (items: Target[], added: TagBrief[], removed: TagBrief[]) => {
    if (!items.length || (!added.length && !removed.length)) return
    const ids = items.map((item) => item.id)
    try {
      const result = await send(
        { action: 'tags', add_tag_ids: added.map((tag) => tag.id), remove_tag_ids: removed.map((tag) => tag.id) },
        ids,
      )
      if (result.skipped.length) toast.error(`Не удалось изменить теги: ${recordingsLabel(result.skipped.length)}`)
    } catch (error) {
      toast.error(recordingErrorMessage(error, 'Не удалось изменить теги'))
    } finally {
      refresh(ids)
    }
  }

  /** Into «Корзина»; undo restores exactly what was deleted. */
  const removeMany = async (items: Target[]) => {
    if (!items.length) return
    const ids = items.map((item) => item.id)
    let result: BulkResult
    try {
      result = await send({ action: 'delete' }, ids)
    } catch (error) {
      toast.error(recordingErrorMessage(error, 'Не удалось удалить'))
      return
    } finally {
      refresh(ids)
    }
    const deleted = result.updated
    if (!deleted.length) {
      toast.error('Не удалось удалить: удалить запись может только её автор или администратор')
      return
    }
    toast.default(`В корзине: ${recordingsLabel(deleted.length)}`, {
      description: result.skipped.length
        ? `Не удалось удалить: ${recordingsLabel(result.skipped.length)}`
        : `Их можно восстановить в корзине в течение ${daysLabel(trashDays.value)}`,
      duration: 8000,
      action: { label: 'Отменить', onClick: () => void restoreMany(deleted) },
    })
  }

  const restoreMany = async (ids: string[]) => {
    if (!ids.length) return
    let result: BulkResult
    try {
      result = await send({ action: 'restore' }, ids)
    } catch (error) {
      toast.error(recordingErrorMessage(error, 'Не удалось восстановить'))
      return
    } finally {
      refresh(ids)
    }
    const restored = result.updated
    if (result.skipped.length)
      toast.error(`Не удалось восстановить: ${recordingsLabel(result.skipped.length)}`, {
        description: 'Восстановить запись может её автор или администратор',
      })
    if (!restored.length) return
    if (restored.length === 1)
      toast.default('Запись восстановлена', {
        action: {
          label: 'Открыть',
          onClick: () => void navigateTo({ name: 'recordings-id', params: { id: restored[0]! } }),
        },
      })
    else toast.default(`Восстановлено: ${recordingsLabel(restored.length)}`)
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
