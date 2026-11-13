import {
  recordingsDestroy,
  recordingsList,
  recordingsPartialUpdate,
  recordingsRetrieve,
  type RecordingDetailSchema,
  type RecordingReadSchema,
  type RecordingStatus,
  type RecordingUpdateSchema,
  type SnippetPartSchema,
  type TagBriefSchema,
  type TranscriptSegmentSchema,
} from '~/shared/api/generated'
import { defineResource } from '~/shared/api/resource'

export type Recording = RecordingReadSchema
export type RecordingDetail = RecordingDetailSchema
export type RecordingPatch = RecordingUpdateSchema
export type TranscriptSegment = TranscriptSegmentSchema
export type SnippetPart = SnippetPartSchema
export type TagBrief = TagBriefSchema
export type { RecordingStatus }

/** List filters of `GET /recordings` the web app uses. */
export type RecordingFilters = {
  project_id?: string
  tag_id?: string
  created_by_id?: string
  status?: RecordingStatus
  personal?: boolean
  search?: string
}

// The detail (`[recordings, id]`) carries the transcript; list rows (`[recordings, list, params]`) do not.
// Edits go through `useRecordingMutations` (PATCH with optimistic updates), not a form.
export const recordingResource = defineResource({
  key: 'recordings',
  sdk: {
    list: recordingsList,
    retrieve: recordingsRetrieve,
    update: recordingsPartialUpdate,
    destroy: recordingsDestroy,
  },
  toForm: (item?: Partial<Recording>) => ({ id: item?.id ?? null }),
})
