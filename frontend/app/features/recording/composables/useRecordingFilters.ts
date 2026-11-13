import type { RecordingFilters, RecordingStatus } from '../resources/recording'

const QUERY_KEYS = {
  search: 'q',
  project_id: 'project',
  tag_id: 'tag',
  created_by_id: 'author',
  status: 'status',
} as const

export type RecordingFilterKey = keyof typeof QUERY_KEYS

/**
 * List filters kept in the URL (`?q=&project=&tag=&author=&status=`), so back navigation and shared links restore
 * them. `fixed` filters belong to the screen (a project page, «Личные») and are not editable.
 */
export const useRecordingFilters = (fixed: () => RecordingFilters) => {
  const route = useRoute()
  const router = useRouter()

  const read = (key: RecordingFilterKey) => {
    const value = route.query[QUERY_KEYS[key]]
    return typeof value === 'string' && value ? value : null
  }
  const write = (key: RecordingFilterKey, value: string | null) => {
    const query = { ...route.query }
    if (value) query[QUERY_KEYS[key]] = value
    else delete query[QUERY_KEYS[key]]
    void router.replace({ query })
  }
  const field = (key: RecordingFilterKey) =>
    computed<string | null>({
      get: () => read(key),
      set: (value) => write(key, value),
    })

  const search = field('search')
  const projectId = field('project_id')
  const tagId = field('tag_id')
  const authorId = field('created_by_id')
  const status = field('status')

  const active = computed(() =>
    (Object.keys(QUERY_KEYS) as RecordingFilterKey[]).some((key) => read(key) && !(key in fixed())),
  )

  const params = computed<RecordingFilters>(() => {
    const result: RecordingFilters = {}
    if (search.value?.trim()) result.search = search.value.trim()
    if (projectId.value) result.project_id = projectId.value
    if (tagId.value) result.tag_id = tagId.value
    if (authorId.value) result.created_by_id = authorId.value
    if (status.value) result.status = status.value as RecordingStatus
    return { ...result, ...fixed() }
  })

  const reset = () => {
    const query = { ...route.query }
    for (const key of Object.values(QUERY_KEYS)) delete query[key]
    void router.replace({ query })
  }

  return { search, projectId, tagId, authorId, status, params, active, reset }
}
