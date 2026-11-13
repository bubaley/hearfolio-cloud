from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from fastapi_ronin.decorators import schema
from pydantic import ConfigDict, Field, computed_field, field_validator

from app.core.models import BaseCreateSchema, BaseReadSchema, BaseSchema
from app.core.settings import settings
from app.domains.library.models import (
    Project,
    ProjectMember,
    ProjectSuggestionState,
    Recording,
    RecordingEvent,
    RecordingEventKind,
    RecordingSource,
    RecordingStatus,
    RecordingVisibility,
    ShareLink,
    Tag,
    TagColor,
    TitleSource,
    UploadState,
    is_stalled_upload,
)
from app.domains.user.models import User


def _as_list(value: Any) -> Any:
    # Tortoise relations (fetched M2M / reverse FK) are iterable but not lists.
    return value if value is None or isinstance(value, list | tuple) else list(value)


# USER_SCHEMAS


@schema(model=User)
class LibraryUserSchema(BaseSchema):
    id: UUID
    first_name: str
    last_name: str
    email: str


# PROJECT_SCHEMAS


@schema(model=Project)
class ProjectCreateSchema(BaseCreateSchema):
    name: str = Field(min_length=1, max_length=255)
    emoji: str | None = Field(None, max_length=32)
    description: str = ''
    is_private: bool = False


@schema(model=Project)
class ProjectUpdateSchema(BaseCreateSchema):
    name: str | None = Field(None, min_length=1, max_length=255)
    emoji: str | None = Field(None, max_length=32)
    description: str | None = None
    # Org admins and the project's creator only
    is_private: bool | None = None
    archived: bool | None = None

    model_config = ConfigDict(extra='forbid')


@schema(model=ProjectMember)
class ProjectMemberReadSchema(BaseReadSchema):
    project_id: UUID
    user_id: UUID
    user: LibraryUserSchema


@schema(model=ProjectMember)
class ProjectMemberCreateSchema(BaseCreateSchema):
    user_id: UUID


@schema(model=Project)
class ProjectBriefSchema(BaseSchema):
    id: UUID
    name: str
    emoji: str | None
    is_private: bool


@schema(model=Project)
class ProjectReadSchema(BaseReadSchema):
    organization_id: UUID
    name: str
    emoji: str | None
    description: str
    is_private: bool
    created_by_id: UUID | None
    archived_at: datetime | None
    # Members of a private project (empty for public ones)
    members: list[ProjectMemberReadSchema]

    _members_list = field_validator('members', mode='before')(_as_list)


# TAG_SCHEMAS


@schema(model=Tag)
class TagCreateSchema(BaseCreateSchema):
    name: str = Field(min_length=1, max_length=64)
    color: TagColor | None = None


@schema(model=Tag)
class TagUpdateSchema(BaseCreateSchema):
    name: str | None = Field(None, min_length=1, max_length=64)
    color: TagColor | None = None

    model_config = ConfigDict(extra='forbid')


@schema(model=Tag)
class TagReadSchema(BaseReadSchema):
    organization_id: UUID
    name: str
    color: TagColor


class TagUsageSchema(BaseSchema):
    """How many recordings visible to the caller carry the tag."""

    tag_id: UUID
    recordings_count: int


class TagMergeSchema(BaseSchema):
    """Move every recording of this tag to `target_id`, then delete this tag."""

    target_id: UUID


@schema(model=Tag)
class TagBriefSchema(BaseSchema):
    id: UUID
    name: str
    color: TagColor


# RECORDING_SCHEMAS


class TranscriptSegmentSchema(BaseSchema):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str


class SnippetPartSchema(BaseSchema):
    text: str
    highlight: bool


@schema(model=Recording)
class RecordingReadSchema(BaseReadSchema):
    """What the list shows. `snippet` is set only by a search: transcript fragment split into highlighted parts."""

    organization_id: UUID
    client_id: UUID
    created_by_id: UUID | None
    created_by: LibraryUserSchema | None
    visibility: RecordingVisibility
    project_id: UUID | None
    project: ProjectBriefSchema | None
    suggested_project_id: UUID | None
    suggested_project: ProjectBriefSchema | None
    project_suggestion_state: ProjectSuggestionState
    tags: list[TagBriefSchema]
    title: str
    title_source: TitleSource
    recorded_at: datetime
    duration_ms: int
    source: RecordingSource
    audio_size: int
    audio_mime: str
    original_filename: str
    upload_state: UploadState
    status: RecordingStatus
    progress: int
    segments_done: int
    segments_total: int
    transcription_model: str | None
    language: str | None
    error_code: str | None
    error_message: str | None
    deleted_at: datetime | None
    snippet: list[SnippetPartSchema] | None = None
    # Set only by a search: where the first transcript segment with a match starts (null without segments or when
    # only the title matched), so a hit can open the recording at that moment
    snippet_start_ms: int | None = None

    _tags_list = field_validator('tags', mode='before')(_as_list)

    @computed_field
    @property
    def stalled(self) -> bool:
        """The upload has not moved for UPLOAD_STALLED_AFTER_HOURS (12 h): the app likely gave up on it."""
        return is_stalled_upload(self.status, self.upload_state, self.updated_at)


@schema(model=Recording)
class RecordingDetailSchema(RecordingReadSchema):
    transcript_text: str
    transcript_segments: list[TranscriptSegmentSchema]


class RecordingCreateSchema(BaseSchema):
    """
    Create a recording before its audio is uploaded. Re-sending the same `client_id` returns the existing recording.
    With `transcript_text` (an already transcribed local recording) no transcription runs.
    """

    client_id: UUID
    title: str | None = Field(None, max_length=255)
    # With a title: `user` (default) keeps AI from renaming it; `auto` marks a generated name («Запись 13.11 10:05»)
    # that the AI title may replace.
    title_source: TitleSource | None = None
    recorded_at: datetime
    duration_ms: int = Field(0, ge=0)
    source: RecordingSource = RecordingSource.DESKTOP
    original_filename: str = Field('', max_length=255)
    audio_mime: str = Field(min_length=1, max_length=128)
    audio_size: int = Field(gt=0)
    project_id: UUID | None = None
    visibility: RecordingVisibility = RecordingVisibility.ORGANIZATION
    tag_ids: list[UUID] = Field(default_factory=list, max_length=20)
    transcript_text: str | None = None
    transcript_segments: list[TranscriptSegmentSchema] | None = None
    transcription_model: str | None = Field(None, max_length=255)
    language: str | None = Field(None, max_length=32)


class RecordingUpdateSchema(BaseSchema):
    """Anyone who sees the recording may rename, move between visible projects and edit tags. Visibility: author only."""

    title: str | None = Field(None, min_length=1, max_length=255)
    # Explicit null moves the recording out of its project
    project_id: UUID | None = None
    tag_ids: list[UUID] | None = Field(None, max_length=20)
    visibility: RecordingVisibility | None = None

    model_config = ConfigDict(extra='forbid')


class RecordingListQuery(BaseSchema):
    project_id: UUID | None = None
    tag_id: UUID | None = None
    created_by_id: UUID | None = None
    status: RecordingStatus | None = None
    # Only the caller's personal recordings
    personal: bool | None = None
    recorded_from: date | None = None
    recorded_to: date | None = None
    # Full-text search over title and transcript
    search: str | None = Field(None, max_length=200)
    # Soft-deleted recordings the caller can see (trash)
    deleted: bool = False
    # Stalled uploads of other users are left out unless asked for (the caller always sees their own)
    include_stalled: bool = False


BULK_MAX_IDS = 200


class RecordingBulkAction(StrEnum):
    MOVE = 'move'
    TAGS = 'tags'
    DELETE = 'delete'
    RESTORE = 'restore'


class RecordingBulkSkipReason(StrEnum):
    # Unknown, invisible to the caller, or not in the state the action needs (deleted for `restore`, live otherwise)
    NOT_FOUND = 'not_found'
    # Visible, but the caller may not do this to it (delete / restore: author or org admin)
    FORBIDDEN = 'forbidden'


class RecordingBulkSchema(BaseSchema):
    """
    One action over up to 200 recordings with the per-recording permissions of the single endpoints.
    `move`: `project_id` (null takes them out of their project). `tags`: `add_tag_ids` / `remove_tag_ids`.
    """

    action: RecordingBulkAction
    ids: list[UUID] = Field(min_length=1, max_length=BULK_MAX_IDS)
    project_id: UUID | None = None
    add_tag_ids: list[UUID] = Field(default_factory=list, max_length=20)
    remove_tag_ids: list[UUID] = Field(default_factory=list, max_length=20)

    model_config = ConfigDict(extra='forbid')


class RecordingBulkSkippedSchema(BaseSchema):
    id: UUID
    reason: RecordingBulkSkipReason


class RecordingBulkResultSchema(BaseSchema):
    """`updated`: the recordings the action applied to (also those already in the wanted state)."""

    updated: list[UUID]
    skipped: list[RecordingBulkSkippedSchema]


class UploadPartSchema(BaseSchema):
    part_number: int
    url: str


class UploadPlanSchema(BaseSchema):
    """
    `single`: PUT the whole file to `url` with the `headers`. `multipart`: PUT each part (`part_size` bytes, the
    last one shorter) to its URL, keep each response's `ETag`, then call `upload/complete`.
    """

    method: Literal['single', 'multipart']
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    upload_id: str | None = None
    part_size: int | None = None
    parts_count: int | None = None
    parts: list[UploadPartSchema] = Field(default_factory=list)
    expires_at: datetime


class RecordingCreatedSchema(BaseSchema):
    recording: RecordingDetailSchema
    # null when the audio is already uploaded (an idempotent re-send) or the recording is deleted
    upload: UploadPlanSchema | None


class UploadPartsRequestSchema(BaseSchema):
    # Omit for every part
    part_numbers: list[int] | None = Field(None, max_length=10_000)


class UploadedPartSchema(BaseSchema):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=256)


class UploadCompleteSchema(BaseSchema):
    # Multipart only; omitted → the server lists the uploaded parts itself
    parts: list[UploadedPartSchema] | None = None


class AudioUrlSchema(BaseSchema):
    url: str
    expires_at: datetime


class RecordingSyncSchema(BaseSchema):
    """
    Changes after `cursor`, ordered by (updated_at, id). `deleted_ids`: recordings the client must drop if it has
    them (deleted, or no longer visible to the caller). Pass `next_cursor` back until `has_more` is false.
    """

    items: list[RecordingDetailSchema]
    deleted_ids: list[UUID]
    next_cursor: str | None
    has_more: bool


# EVENT_SCHEMAS


@schema(model=RecordingEvent)
class RecordingEventReadSchema(BaseReadSchema):
    recording_id: UUID
    actor_id: UUID | None
    actor: LibraryUserSchema | None
    kind: RecordingEventKind
    data: dict[str, Any]


# SHARE_LINK_SCHEMAS


class ShareLinkUpsertSchema(BaseSchema):
    include_audio: bool = True
    include_transcript: bool = True
    result_ids: list[UUID] = Field(default_factory=list, max_length=50)
    expires_at: datetime | None = None


@schema(model=ShareLink)
class ShareLinkReadSchema(BaseReadSchema):
    recording_id: UUID
    token: str
    include_audio: bool
    include_transcript: bool
    result_ids: list[UUID]
    expires_at: datetime | None
    revoked_at: datetime | None
    created_by_id: UUID | None
    views: int

    @computed_field
    @property
    def url(self) -> str | None:
        """The public page `{PUBLIC_URL}/s/{token}`; null when PUBLIC_URL is not configured."""
        return f'{settings.public_url.rstrip("/")}/s/{self.token}' if settings.public_url else None


class PublicShareSchema(BaseSchema):
    """Exactly what the link exposes; `audio` is a short-lived presigned URL."""

    title: str
    recorded_at: datetime
    duration_ms: int
    language: str | None
    audio: AudioUrlSchema | None
    transcript_text: str | None
    transcript_segments: list[TranscriptSegmentSchema] | None
    # Filled by the ai domain (RecordingPipeline.register_share_results_provider)
    results: list[dict[str, Any]]
