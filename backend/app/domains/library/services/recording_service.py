from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.services.s3_service import get_s3_service
from app.core.settings import settings
from app.core.utils.date_utils import utcnow
from app.domains.library.models import (
    Project,
    ProjectSuggestionState,
    Recording,
    RecordingEvent,
    RecordingEventKind,
    RecordingStatus,
    RecordingVisibility,
    Tag,
    TitleSource,
    UploadState,
)
from app.domains.library.schemas import AudioUrlSchema, RecordingUpdateSchema, TranscriptSegmentSchema
from app.domains.library.services.pipeline import RecordingPipeline
from app.domains.library.services.realtime import LibraryRealtime
from app.domains.library.services.tag_service import TagService
from app.domains.library.services.visibility import LibraryVisibility
from app.domains.organization.services.organization_service import OrganizationService
from app.domains.user.models import User

AI_TAGS_LIMIT = 5
TITLE_MAX_LENGTH = 255


class RecordingUpdateData(BaseModel):
    """A validated PATCH: only the keys present are applied."""

    title: str | None = None
    project: Project | None = None
    tags: list[Tag] | None = None
    visibility: RecordingVisibility | None = None
    fields_set: set[str]

    model_config = ConfigDict(arbitrary_types_allowed=True)


def _segments_text(segments: list[dict[str, Any]]) -> str:
    return '\n'.join(text for segment in segments if (text := str(segment.get('text', '')).strip()))


class RecordingService:
    """
    Every change to a recording goes through this class: it saves only the changed columns (plus `updated_at`,
    which drives /recordings/sync), writes the journal and publishes `recording.updated` / `recording.deleted`.
    The methods under PIPELINE are the API of the processing pipeline (docs/pipeline-seam.md).
    """

    # JOURNAL AND SAVING

    @staticmethod
    async def record_event(
        recording: Recording, kind: RecordingEventKind, actor: User | None = None, data: dict[str, Any] | None = None
    ) -> RecordingEvent:
        return await RecordingEvent.create(
            recording_id=recording.id,
            actor_id=actor.id if actor else None,
            kind=kind,
            data=jsonable_encoder(data or {}),
        )

    @staticmethod
    async def _save(recording: Recording, *fields: str) -> None:
        recording.updated_at = utcnow()
        await recording.save(update_fields=[*fields, 'updated_at'])

    @staticmethod
    async def _touch(recording: Recording) -> None:
        recording.updated_at = utcnow()
        await Recording.filter(id=recording.id).update(updated_at=recording.updated_at)

    # USER WORKFLOWS

    @staticmethod
    async def is_admin(user: User, recording: Recording) -> bool:
        return await OrganizationService.is_admin(user, recording.organization_id)

    @classmethod
    async def validate_project(cls, project_id: UUID, recording_organization_id: UUID, actor: User) -> Project:
        project = await LibraryVisibility.projects(actor, recording_organization_id).get_or_none(id=project_id)
        if project is None:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Project not found')
        return project

    @staticmethod
    async def validate_tags(tag_ids: list[UUID], organization_id: UUID) -> list[Tag]:
        unique_ids = list(dict.fromkeys(tag_ids))
        tags = await Tag.filter(organization_id=organization_id, id__in=unique_ids)
        if len(tags) != len(unique_ids):
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Tag not found')
        return tags

    @classmethod
    async def validate_update(
        cls, recording: Recording, data: RecordingUpdateSchema, actor: User
    ) -> RecordingUpdateData:
        fields_set = set(data.model_fields_set)
        result = RecordingUpdateData(fields_set=fields_set)
        if 'title' in fields_set:
            title = ' '.join((data.title or '').split())
            if not title:
                raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Title is empty')
            result.title = title
        if 'project_id' in fields_set and data.project_id is not None and data.project_id != recording.project_id:
            result.project = await cls.validate_project(data.project_id, recording.organization_id, actor)
        if 'tag_ids' in fields_set:
            result.tags = await cls.validate_tags(data.tag_ids or [], recording.organization_id)
        if 'visibility' in fields_set and data.visibility is not None:
            if data.visibility != recording.visibility and recording.created_by_id != actor.id:
                raise AppException.from_attrs(ErrorCode.FORBIDDEN, 'Only the author can change who sees a recording')
            result.visibility = data.visibility
        return result

    @classmethod
    async def update(cls, recording: Recording, data: RecordingUpdateData, actor: User) -> Recording:
        changed: list[str] = []
        events: list[tuple[RecordingEventKind, dict[str, Any]]] = []
        if data.title is not None and data.title != recording.title:
            events.append((RecordingEventKind.RENAMED, {'from': recording.title, 'to': data.title}))
            recording.title = data.title
            recording.title_source = TitleSource.USER
            changed += ['title', 'title_source']
        if 'project_id' in data.fields_set:
            new_project_id = data.project.id if data.project else None
            if new_project_id != recording.project_id:
                events.append(
                    (
                        RecordingEventKind.MOVED,
                        {'from_project_id': recording.project_id, 'to_project_id': new_project_id},
                    )
                )
                recording.project_id = new_project_id
                changed.append('project_id')
                if recording.project_suggestion_state == ProjectSuggestionState.PENDING:
                    recording.project_suggestion_state = (
                        ProjectSuggestionState.ACCEPTED
                        if new_project_id and new_project_id == recording.suggested_project_id
                        else ProjectSuggestionState.DISMISSED
                    )
                    changed.append('project_suggestion_state')
        if data.visibility is not None and data.visibility != recording.visibility:
            recording.visibility = data.visibility
            changed.append('visibility')

        async with in_transaction():
            if data.tags is not None and (tag_event := await cls._set_tags(recording, data.tags)):
                events.append((RecordingEventKind.TAGGED, tag_event))
            if changed:
                await cls._save(recording, *changed)
            elif events:
                await cls._touch(recording)
            for kind, event_data in events:
                await cls.record_event(recording, kind, actor, event_data)
        if changed or events:
            await LibraryRealtime.recording_updated(recording)
        return recording

    @staticmethod
    async def _set_tags(recording: Recording, tags: list[Tag]) -> dict[str, Any] | None:
        current = {tag.id: tag for tag in await recording.tags.all()}
        wanted = {tag.id: tag for tag in tags}
        added = [tag for tag_id, tag in wanted.items() if tag_id not in current]
        removed = [tag for tag_id, tag in current.items() if tag_id not in wanted]
        if removed:
            await recording.tags.remove(*removed)
        if added:
            await recording.tags.add(*added)
        if not added and not removed:
            return None
        return {'added': [tag.name for tag in added], 'removed': [tag.name for tag in removed]}

    @classmethod
    async def validate_delete(cls, recording: Recording, actor: User) -> None:
        if recording.created_by_id != actor.id and not await cls.is_admin(actor, recording):
            raise AppException.from_attrs(ErrorCode.FORBIDDEN, 'Only the author or an admin can delete a recording')

    @classmethod
    async def delete(cls, recording: Recording, actor: User) -> None:
        """Soft delete: a tombstone for app sync; purged with its audio after RECORDING_PURGE_AFTER_DAYS."""
        await cls.validate_delete(recording, actor)
        if recording.deleted_at is not None:
            return
        recording.deleted_at = utcnow()
        async with in_transaction():
            await cls._save(recording, 'deleted_at')
            await cls.record_event(recording, RecordingEventKind.DELETED, actor)
        await LibraryRealtime.recording_deleted(recording)

    @classmethod
    async def restore(cls, recording: Recording, actor: User) -> Recording:
        await cls.validate_delete(recording, actor)
        if recording.deleted_at is None:
            return recording
        recording.deleted_at = None
        async with in_transaction():
            await cls._save(recording, 'deleted_at')
            await cls.record_event(recording, RecordingEventKind.RESTORED, actor)
        await LibraryRealtime.recording_updated(recording)
        return recording

    @classmethod
    async def resolve_project_suggestion(cls, recording: Recording, accept: bool, actor: User) -> Recording:
        """The «Похоже на проект X» banner: [Перенести] moves the recording, [Нет] dismisses the suggestion."""
        if recording.project_suggestion_state != ProjectSuggestionState.PENDING or not recording.suggested_project_id:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'No pending project suggestion')
        if not accept:
            recording.project_suggestion_state = ProjectSuggestionState.DISMISSED
            await cls._save(recording, 'project_suggestion_state')
            await LibraryRealtime.recording_updated(recording)
            return recording
        project = await cls.validate_project(recording.suggested_project_id, recording.organization_id, actor)
        data = RecordingUpdateData(project=project, fields_set={'project_id'})
        return await cls.update(recording, data, actor)

    @staticmethod
    async def audio_url(recording: Recording, download: bool = False) -> AudioUrlSchema:
        if recording.upload_state != UploadState.UPLOADED:
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, 'Audio is not uploaded yet')
        expires_in = settings.aws_s3_presign_expire_seconds
        download_name = None
        if download:
            extension = recording.audio_key.rsplit('.', 1)[-1] if '.' in recording.audio_key.rsplit('/', 1)[-1] else ''
            base = recording.title or recording.original_filename or 'recording'
            download_name = f'{base}.{extension}' if extension and not base.endswith(f'.{extension}') else base
        url = await get_s3_service().presigned_get_url(
            recording.audio_key, expires_in=expires_in, download_name=download_name
        )
        return AudioUrlSchema(url=url, expires_at=utcnow() + timedelta(seconds=expires_in))

    # PIPELINE (docs/pipeline-seam.md). `recording` is a fresh instance; no actor: the journal shows AI/system.

    @classmethod
    async def mark_uploaded(cls, recording: Recording, actor: User | None = None) -> Recording:
        """The audio is in S3: set `uploaded`, queue processing (unless a transcript came with the recording)."""
        recording.upload_state = UploadState.UPLOADED
        recording.upload_id = None
        fields = ['upload_state', 'upload_id']
        if recording.status in (RecordingStatus.AWAITING_UPLOAD, RecordingStatus.FAILED):
            recording.status = RecordingStatus.QUEUED
            recording.error_code = None
            recording.error_message = None
            fields += ['status', 'error_code', 'error_message']
        async with in_transaction():
            await cls._save(recording, *fields)
            await cls.record_event(recording, RecordingEventKind.UPLOADED, actor, {'size': recording.audio_size})
        await LibraryRealtime.recording_updated(recording)
        await RecordingPipeline.enqueue(recording)
        return recording

    @classmethod
    async def start_transcription(
        cls, recording: Recording, *, model: str | None, segments_total: int, language: str | None = None
    ) -> Recording:
        recording.status = RecordingStatus.TRANSCRIBING
        recording.segments_total = max(segments_total, 0)
        recording.segments_done = min(recording.segments_done, recording.segments_total)
        recording.progress = cls._progress(recording.segments_done, recording.segments_total)
        recording.transcription_model = model
        recording.error_code = None
        recording.error_message = None
        fields = ['status', 'segments_total', 'segments_done', 'progress', 'transcription_model']
        fields += ['error_code', 'error_message']
        if language is not None:
            recording.language = language
            fields.append('language')
        await cls._save(recording, *fields)
        await LibraryRealtime.recording_updated(recording)
        return recording

    @staticmethod
    def _progress(done: int, total: int) -> int:
        if total <= 0:
            return 0
        return max(0, min(100, round(100 * done / total)))

    @classmethod
    async def update_progress(
        cls, recording: Recording, *, segments_done: int, segments_total: int | None = None
    ) -> Recording:
        if segments_total is not None:
            recording.segments_total = segments_total
        recording.segments_done = segments_done
        recording.progress = cls._progress(recording.segments_done, recording.segments_total)
        await cls._save(recording, 'segments_done', 'segments_total', 'progress')
        await LibraryRealtime.recording_updated(recording)
        return recording

    @classmethod
    async def save_segments(
        cls,
        recording: Recording,
        segments: list[TranscriptSegmentSchema],
        *,
        segments_done: int,
        segments_total: int | None = None,
    ) -> Recording:
        """
        Append the segments of one finished audio chunk to the live transcript and advance progress. Segments that
        start before the end of the saved transcript are dropped, so re-running a chunk never duplicates text.
        """
        existing: list[dict[str, Any]] = list(recording.transcript_segments or [])
        last_end = max((int(segment.get('end_ms', 0)) for segment in existing), default=-1)
        new = [segment.model_dump() for segment in segments if segment.start_ms >= last_end]
        recording.transcript_segments = existing + new
        recording.transcript_text = _segments_text(recording.transcript_segments)
        if segments_total is not None:
            recording.segments_total = segments_total
        recording.segments_done = segments_done
        recording.progress = cls._progress(recording.segments_done, recording.segments_total)
        await cls._save(
            recording, 'transcript_segments', 'transcript_text', 'segments_done', 'segments_total', 'progress'
        )
        await LibraryRealtime.recording_updated(recording)
        return recording

    @classmethod
    async def set_transcript(
        cls,
        recording: Recording,
        *,
        segments: list[TranscriptSegmentSchema],
        text: str | None = None,
        model: str | None = None,
        language: str | None = None,
    ) -> Recording:
        """Replace the transcript at once (a finished re-transcription) and mark the recording `transcribed`."""
        recording.transcript_segments = [segment.model_dump() for segment in segments]
        recording.transcript_text = text if text is not None else _segments_text(recording.transcript_segments)
        return await cls.mark_transcribed(recording, model=model, language=language)

    @classmethod
    async def mark_transcribed(
        cls, recording: Recording, *, model: str | None = None, language: str | None = None
    ) -> Recording:
        recording.status = RecordingStatus.TRANSCRIBED
        recording.progress = 100
        recording.segments_done = recording.segments_total
        recording.error_code = None
        recording.error_message = None
        fields = ['transcript_segments', 'transcript_text', 'status', 'progress', 'segments_done']
        fields += ['error_code', 'error_message']
        if model is not None:
            recording.transcription_model = model
            fields.append('transcription_model')
        if language is not None:
            recording.language = language
            fields.append('language')
        async with in_transaction():
            await cls._save(recording, *fields)
            await cls.record_event(recording, RecordingEventKind.TRANSCRIBED, None, {'model': model})
        await LibraryRealtime.recording_updated(recording)
        return recording

    @classmethod
    async def set_failed(cls, recording: Recording, *, code: str, message: str) -> Recording:
        """`message` is shown to users: human-readable Russian, never raw provider output. Finished segments stay."""
        recording.status = RecordingStatus.FAILED
        recording.error_code = code[:64]
        recording.error_message = message[:2000]
        async with in_transaction():
            await cls._save(recording, 'status', 'error_code', 'error_message')
            await cls.record_event(recording, RecordingEventKind.FAILED, None, {'code': code, 'message': message})
        await LibraryRealtime.recording_updated(recording)
        return recording

    @classmethod
    async def set_title_from_ai(cls, recording: Recording, title: str) -> bool:
        """Set an AI title unless a user has renamed the recording. Returns whether the title changed."""
        title = ' '.join(title.split())[:TITLE_MAX_LENGTH]
        if not title or recording.title_source == TitleSource.USER or title == recording.title:
            return False
        # Re-check in the database: a user may have renamed it while the pipeline was running.
        updated = await Recording.filter(id=recording.id, title_source=TitleSource.AUTO).update(
            title=title, updated_at=utcnow()
        )
        if not updated:
            return False
        previous = recording.title
        await recording.refresh_from_db()
        await cls.record_event(recording, RecordingEventKind.RENAMED, None, {'from': previous, 'to': title})
        await LibraryRealtime.recording_updated(recording)
        return True

    @classmethod
    async def apply_ai_tags(cls, recording: Recording, names: list[str]) -> list[Tag]:
        """
        Add up to 5 tags by name (existing org tags are reused case-insensitively, missing ones created). Tags
        already on the recording stay; returns the tags that were added.
        """
        tags = await TagService.get_or_create_many(recording.organization_id, names, limit=AI_TAGS_LIMIT)
        current_ids = set(await recording.tags.all().values_list('id', flat=True))
        added = [tag for tag in tags if tag.id not in current_ids]
        if not added:
            return []
        async with in_transaction():
            await recording.tags.add(*added)
            await cls._touch(recording)
            await cls.record_event(
                recording, RecordingEventKind.TAGGED, None, {'added': [tag.name for tag in added], 'removed': []}
            )
        await LibraryRealtime.recording_updated(recording)
        return added

    @classmethod
    async def suggest_project(cls, recording: Recording, project: Project) -> bool:
        """
        Offer `project` (the user confirms). Ignored when the recording already has a project, the suggestion was
        already answered, or the author cannot see the project.
        """
        if recording.project_id is not None or project.organization_id != recording.organization_id:
            return False
        if recording.project_suggestion_state in (ProjectSuggestionState.ACCEPTED, ProjectSuggestionState.DISMISSED):
            return False
        author = await User.get_or_none(id=recording.created_by_id) if recording.created_by_id else None
        if author is None or not await LibraryVisibility.can_see_project(author, project):
            return False
        recording.suggested_project_id = project.id
        recording.project_suggestion_state = ProjectSuggestionState.PENDING
        await cls._save(recording, 'suggested_project_id', 'project_suggestion_state')
        await LibraryRealtime.recording_updated(recording)
        return True

    @classmethod
    async def touch_for_result(cls, recording: Recording) -> None:
        """A summary of the recording changed: bump `updated_at` (sync carries results metadata) and notify."""
        await cls._touch(recording)
        await LibraryRealtime.recording_updated(recording)
