from enum import StrEnum
from typing import Any
from uuid import UUID

from tortoise import fields
from tortoise.contrib.postgres.fields import TSVectorField
from tortoise.expressions import Q, Subquery

from app.core.models import BaseModel
from app.core.scope import Scope
from app.domains.organization.models import OrganizationUser


def _member_organizations(user_id: UUID) -> Q:
    # A subquery instead of 'organization__org_users__user_id': one EXISTS-like filter, no row multiplication.
    return Q(organization_id__in=Subquery(OrganizationUser.filter(user_id=user_id).values('organization_id')))


def _member_organizations_of_recording(user_id: UUID) -> Q:
    member_org_ids = OrganizationUser.filter(user_id=user_id).values('organization_id')
    return Q(recording__organization_id__in=Subquery(member_org_ids))


def _member_organizations_of_project(user_id: UUID) -> Q:
    member_org_ids = OrganizationUser.filter(user_id=user_id).values('organization_id')
    return Q(project__organization_id__in=Subquery(member_org_ids))


# The tenant scopes below only keep rows inside the caller's organizations. Who sees which project or
# recording inside an organization is decided by ProjectService.visible_projects / RecordingAccess.visible.


class Project(BaseModel):
    organization = fields.ForeignKeyField('models.Organization', related_name='projects', on_delete=fields.CASCADE)
    organization_id: UUID
    name = fields.CharField(max_length=255)
    emoji = fields.CharField(max_length=32, null=True)
    description = fields.TextField(default='')
    is_private = fields.BooleanField(default=False)
    created_by = fields.ForeignKeyField(
        'models.User', related_name='created_projects', null=True, on_delete=fields.SET_NULL
    )
    created_by_id: UUID | None
    archived_at = fields.DatetimeField(null=True)

    members: fields.ReverseRelation[ProjectMember]

    tenant_scope = Scope(user=_member_organizations, organization='organization_id')

    class Meta:
        table = 'project'
        ordering = ('name',)


class ProjectMember(BaseModel):
    project = fields.ForeignKeyField('models.Project', related_name='members', on_delete=fields.CASCADE)
    project_id: UUID
    user = fields.ForeignKeyField('models.User', related_name='project_memberships', on_delete=fields.CASCADE)
    user_id: UUID

    tenant_scope = Scope(user=_member_organizations_of_project, organization='project__organization_id')

    class Meta:
        table = 'project_member'
        unique_together = (('project', 'user'),)
        ordering = ('created_at',)


class TagColor(StrEnum):
    GRAY = 'gray'
    BROWN = 'brown'
    ORANGE = 'orange'
    YELLOW = 'yellow'
    GREEN = 'green'
    BLUE = 'blue'
    PURPLE = 'purple'
    PINK = 'pink'
    RED = 'red'


class Tag(BaseModel):
    organization = fields.ForeignKeyField('models.Organization', related_name='tags', on_delete=fields.CASCADE)
    organization_id: UUID
    name = fields.CharField(max_length=64)
    # casefold(name): uniqueness per organization is case-insensitive
    name_key = fields.CharField(max_length=64)
    color = fields.CharEnumField(TagColor, max_length=16, default=TagColor.GRAY)

    recordings: fields.ManyToManyRelation[Recording]

    tenant_scope = Scope(user=_member_organizations, organization='organization_id')

    class Meta:
        table = 'tag'
        unique_together = (('organization', 'name_key'),)
        ordering = ('name',)


class RecordingVisibility(StrEnum):
    ORGANIZATION = 'organization'
    PERSONAL = 'personal'


class ProjectSuggestionState(StrEnum):
    NONE = 'none'
    PENDING = 'pending'
    ACCEPTED = 'accepted'
    DISMISSED = 'dismissed'


class TitleSource(StrEnum):
    AUTO = 'auto'
    USER = 'user'


class RecordingSource(StrEnum):
    DESKTOP = 'desktop'
    ANDROID = 'android'
    WEB = 'web'
    IMPORT = 'import'


class UploadState(StrEnum):
    PENDING = 'pending'
    UPLOADING = 'uploading'
    UPLOADED = 'uploaded'
    FAILED = 'failed'


class RecordingStatus(StrEnum):
    AWAITING_UPLOAD = 'awaiting_upload'
    QUEUED = 'queued'
    TRANSCRIBING = 'transcribing'
    TRANSCRIBED = 'transcribed'
    FAILED = 'failed'


class Recording(BaseModel):
    organization = fields.ForeignKeyField('models.Organization', related_name='recordings', on_delete=fields.CASCADE)
    organization_id: UUID
    # Idempotency key from the app
    client_id = fields.UUIDField()
    created_by = fields.ForeignKeyField('models.User', related_name='recordings', null=True, on_delete=fields.SET_NULL)
    created_by_id: UUID | None
    visibility = fields.CharEnumField(RecordingVisibility, max_length=16, default=RecordingVisibility.ORGANIZATION)
    project = fields.ForeignKeyField('models.Project', related_name='recordings', null=True, on_delete=fields.SET_NULL)
    project_id: UUID | None
    suggested_project = fields.ForeignKeyField(
        'models.Project', related_name='suggested_recordings', null=True, on_delete=fields.SET_NULL
    )
    suggested_project_id: UUID | None
    project_suggestion_state = fields.CharEnumField(
        ProjectSuggestionState, max_length=16, default=ProjectSuggestionState.NONE
    )
    tags: fields.ManyToManyRelation[Tag] = fields.ManyToManyField(
        'models.Tag', related_name='recordings', through='recording_tag'
    )

    title = fields.CharField(max_length=255, default='')
    title_source = fields.CharEnumField(TitleSource, max_length=8, default=TitleSource.AUTO)
    recorded_at = fields.DatetimeField(db_index=True)
    duration_ms = fields.BigIntField(default=0)
    source = fields.CharEnumField(RecordingSource, max_length=16, default=RecordingSource.DESKTOP)

    audio_key = fields.CharField(max_length=512)
    audio_size = fields.BigIntField()
    audio_mime = fields.CharField(max_length=128)
    original_filename = fields.CharField(max_length=255, default='')
    upload_state = fields.CharEnumField(UploadState, max_length=16, default=UploadState.PENDING)
    # S3 multipart upload in progress (null for a single PUT)
    upload_id = fields.CharField(max_length=1024, null=True)
    upload_part_size = fields.BigIntField(null=True)

    status = fields.CharEnumField(RecordingStatus, max_length=16, default=RecordingStatus.AWAITING_UPLOAD)
    progress = fields.SmallIntField(default=0)
    segments_done = fields.IntField(default=0)
    segments_total = fields.IntField(default=0)
    transcript_text = fields.TextField(default='')
    # [{start_ms, end_ms, text}]
    transcript_segments: Any = fields.JSONField(default=list)
    transcription_model = fields.CharField(max_length=255, null=True)
    language = fields.CharField(max_length=32, null=True)
    error_code = fields.CharField(max_length=64, null=True)
    error_message = fields.CharField(max_length=2000, null=True)

    # Generated column on PostgreSQL (GIN-indexed full-text search); a plain unused column on SQLite.
    search_vector = TSVectorField(source_fields=('title', 'transcript_text'), config='simple', null=True)

    deleted_at = fields.DatetimeField(null=True, db_index=True)

    tenant_scope = Scope(user=_member_organizations, organization='organization_id')

    class Meta:
        table = 'recording'
        ordering = ('-recorded_at',)
        unique_together = (('organization', 'client_id'),)


class ShareLink(BaseModel):
    recording = fields.ForeignKeyField('models.Recording', related_name='share_links', on_delete=fields.CASCADE)
    recording_id: UUID
    token = fields.CharField(max_length=64, unique=True)
    include_audio = fields.BooleanField(default=True)
    include_transcript = fields.BooleanField(default=True)
    # RecordingResult ids (ai domain) exposed by the link
    result_ids: Any = fields.JSONField(default=list)
    expires_at = fields.DatetimeField(null=True)
    revoked_at = fields.DatetimeField(null=True)
    created_by = fields.ForeignKeyField('models.User', related_name='share_links', null=True, on_delete=fields.SET_NULL)
    created_by_id: UUID | None
    views = fields.IntField(default=0)

    tenant_scope = Scope(user=_member_organizations_of_recording, organization='recording__organization_id')

    class Meta:
        table = 'share_link'
        ordering = ('-created_at',)


class RecordingEventKind(StrEnum):
    CREATED = 'created'
    UPLOADED = 'uploaded'
    TRANSCRIBED = 'transcribed'
    FAILED = 'failed'
    RENAMED = 'renamed'
    MOVED = 'moved'
    TAGGED = 'tagged'
    SHARED = 'shared'
    UNSHARED = 'unshared'
    RESULT_CREATED = 'result_created'
    RESTORED = 'restored'
    DELETED = 'deleted'


class RecordingEvent(BaseModel):
    recording = fields.ForeignKeyField('models.Recording', related_name='events', on_delete=fields.CASCADE)
    recording_id: UUID
    # null: AI / system
    actor = fields.ForeignKeyField('models.User', related_name='recording_events', null=True, on_delete=fields.SET_NULL)
    actor_id: UUID | None
    kind = fields.CharEnumField(RecordingEventKind, max_length=32)
    data: Any = fields.JSONField(default=dict)

    tenant_scope = Scope(user=_member_organizations_of_recording, organization='recording__organization_id')

    class Meta:
        table = 'recording_event'
        ordering = ('-created_at',)
