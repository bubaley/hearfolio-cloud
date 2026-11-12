# Pipeline seam: library ↔ ai

The `library` domain owns recordings (models, visibility, upload, journal, realtime). The `ai` domain owns the processing pipeline (transcription, title, tags, project suggestion, summaries). `library` never imports `ai`; `ai` imports `library` services. All of it lives in `backend/app/domains/library/services/pipeline.py` and `recording_service.py`.

## Library → ai

| Hook | Contract |
|---|---|
| Task `ai.process_recording(recording_id: str)` | Kicked by name (`RecordingPipeline.enqueue`, constant `PROCESS_RECORDING_TASK`) once per successful `POST /recordings/{id}/upload/complete`, after `upload_state=uploaded` and `status=queued` (or `transcribed` when the app sent a transcript). The ai task decides from `OrganizationSettings` what to run; with `auto_transcribe=false` it leaves the recording as is. «Повторить» / re-transcribe from the ai endpoints kick it again themselves. In tests (in-memory broker) nothing runs unless the task is registered in the process |
| `RecordingPipeline.register_share_results_provider(provider)` | `provider(recording, result_ids: list[UUID]) -> list[dict]` (awaitable). Returns the summaries a public link exposes, in display order, JSON-serializable (e.g. `{id, title, content, model, created_at}`), only `done` ones among `result_ids`. Register at import time of an ai module the API process imports (`ai/views.py`). Without a provider `results` is `[]` |
| `RecordingPipeline.register_result_ids_checker(checker)` | `checker(recording, result_ids: list[UUID]) -> set[UUID]` (awaitable): the ids among `result_ids` that are results of the recording. `PUT /recordings/{id}/share` rejects other ids (400 `unknown_result_ids`). Without a checker every id is unknown. Registered in `ai/views.py` (`ResultService.result_ids_of`) |

## ai → library: `RecordingService` (all `@classmethod`, `async`)

Load a fresh `Recording` in the task (`await Recording.get(id=...)`) and pass the instance. Each call saves only its columns plus `updated_at` (which drives `/recordings/sync`), writes the journal where noted (actor = AI/system) and publishes `recording.updated` on the organization channel.

| Method | Effect |
|---|---|
| `start_transcription(recording, *, model: str \| None, segments_total: int, language: str \| None = None)` | `status=transcribing`, totals, clears the error |
| `update_progress(recording, *, segments_done: int, segments_total: int \| None = None)` | Progress only (0–100 from done/total) |
| `save_segments(recording, segments: list[TranscriptSegmentSchema], *, segments_done: int, segments_total: int \| None = None)` | Appends one finished chunk to `transcript_segments`/`transcript_text` and advances progress. Segments starting before the end of the saved transcript are dropped, so re-running a chunk after a crash never duplicates text |
| `set_transcript(recording, *, segments, text=None, model=None, language=None)` | Replaces the whole transcript (finished re-transcription: keep the old one until the new one succeeds) and marks it transcribed |
| `mark_transcribed(recording, *, model=None, language=None)` | `status=transcribed`, `progress=100`; journal `transcribed` |
| `set_failed(recording, *, code: str, message: str)` | `status=failed`, keeps finished segments; `message` is Russian and user-facing; journal `failed` |
| `set_title_from_ai(recording, title: str) -> bool` | Sets the title unless `title_source=user` (re-checked in the database, so a rename during processing wins); journal `renamed` |
| `apply_ai_tags(recording, names: list[str]) -> list[Tag]` | Up to 5 names; existing org tags reused case-insensitively, missing ones created (no tags beyond the cap); existing tags stay; returns the added ones; journal `tagged` |
| `suggest_project(recording, project: Project) -> bool` | Sets `suggested_project` + `pending` unless the recording has a project, the suggestion was answered, or the author cannot see the project. Other viewers who cannot see the project get it redacted by `RecordingPresenter` (null, state `none`) |
| `record_event(recording, kind: RecordingEventKind, actor: User \| None = None, data: dict \| None = None)` | Journal entry, e.g. `RESULT_CREATED` with `{result_id, title}` |
| `touch_for_result(recording)` | A summary changed: bump `updated_at` and notify, so sync and clients refetch |

Helpers the pipeline may use: `TagService.get_or_create_many(organization_id, names, limit=None)`, `LibraryVisibility.projects(user, organization_id)` (the projects visible to the author, for the classification prompt), `get_s3_service().presigned_get_url(recording.audio_key)` / the boto client for downloading audio.

## Realtime

`LibraryRealtime` (`services/realtime.py`): `recording.updated` / `recording.deleted` with `{id, updated_at}`; bulk changes over 50 recordings send `recordings.resync`. The ai domain sends its own `result.updated` the same way (minimal payload, clients refetch through the visibility-checked API).

## The ai side

- Tasks in `ai/tasks.py`: `ai.process_recording(recording_id: str, force: bool = False, attempt: int = 0)` (`RecordingProcessor`), `ai.generate_result(result_id: str)` (`ResultService.generate`) and the periodic `ai.requeue_stale_results` (every 5 min: results `running` for over 15 min go back to `queued` and are kicked again; `generate` itself also takes over such a result).
- Lock protocol (`ProcessingLock`, Redis): a run that finds the lock held calls `mark_pending(force)`, tries once more, and returns; the holder releases, then `take_pending()` and runs again if something is pending, so requests during post-processing are never acked and lost. Redis errors raise `LockUnavailableError`: nothing runs, the task is rescheduled through the Redis schedule source (`AITaskKicker.kick_later`, 30 s × 2^attempt, at most 5 attempts). Process memory is used only in tests. The API process kicks them by name (`AITaskKicker`, like `RecordingPipeline.enqueue`) and never imports the pipeline code.
- Per-recording bookkeeping lives in `RecordingProcessing` (ai): which post-transcription steps are done, and a pending re-transcription's model and chunks.
- Results metadata is not part of `RecordingDetailSchema`: clients read `GET /recordings/{id}/results` or `GET /recording-results?updated_after=`; result changes call `touch_for_result` so sync reports the recording (docs/product.md, RecordingResult).
- Retry / re-transcribe (`POST /recordings/{id}/retry`, `/retranscribe`) load the recording through `LibraryVisibility.recordings` and answer with `RecordingPresenter.detail` (per-viewer project redaction).
- `RecordingResult.error_code` is a stable `AIErrorCode` value (`internal` for unexpected failures); `Recording.error_code` from the pipeline is the same set plus `storage` / `audio`. The list for clients is in docs/product.md.
- Automatic summaries skip templates that already have an automatic result for the recording, so a crash between creating them and the `summarized` flag does not duplicate them.
