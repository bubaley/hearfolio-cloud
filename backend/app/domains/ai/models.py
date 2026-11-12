from enum import StrEnum
from typing import Any
from uuid import UUID

from tortoise import fields
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q, Subquery
from tortoise.signals import post_save

from app.core.models import BaseModel
from app.core.scope import Scope
from app.domains.ai.services.openrouter_client import DEFAULT_BASE_URL
from app.domains.organization.models import Organization, OrganizationUser

DEFAULT_SEGMENT_SECONDS = 300
MIN_SEGMENT_SECONDS = 60
MAX_SEGMENT_SECONDS = 900


class OrganizationSettings(BaseModel):
    """AI configuration of one organization; created lazily with defaults (`OrganizationSettingsService.ensure`)."""

    organization = fields.OneToOneField('models.Organization', related_name='ai_settings', on_delete=fields.CASCADE)
    organization_id: UUID
    openrouter_base_url = fields.CharField(max_length=512, default=DEFAULT_BASE_URL)
    # Fernet ciphertext from CryptoService; never serialized.
    openrouter_api_key_encrypted = fields.TextField(default='')
    openrouter_api_key_hint = fields.CharField(max_length=8, default='')
    transcription_models = fields.JSONField(default=list)
    transcription_default_model = fields.CharField(max_length=255, null=True)
    summary_models = fields.JSONField(default=list)
    summary_default_model = fields.CharField(max_length=255, null=True)
    auto_transcribe = fields.BooleanField(default=True)
    auto_title = fields.BooleanField(default=True)
    auto_tags = fields.BooleanField(default=True)
    auto_project = fields.BooleanField(default=True)
    segment_seconds = fields.IntField(default=DEFAULT_SEGMENT_SECONDS)
    language = fields.CharField(max_length=16, default='auto')

    tenant_scope = Scope(user='organization__org_users__user_id', organization='organization_id')

    class Meta:
        table = 'organization_settings'


class SummaryTemplate(BaseModel):
    organization = fields.ForeignKeyField(
        'models.Organization', related_name='summary_templates', on_delete=fields.CASCADE
    )
    organization_id: UUID
    name = fields.CharField(max_length=128)
    prompt = fields.TextField()
    auto = fields.BooleanField(default=False)
    position = fields.IntField(default=0)
    created_by = fields.ForeignKeyField(
        'models.User', related_name='summary_templates', on_delete=fields.SET_NULL, null=True
    )
    created_by_id: UUID | None

    tenant_scope = Scope(user='organization__org_users__user_id', organization='organization_id')

    class Meta:
        table = 'summary_template'
        ordering = ('position', 'created_at')


def _member_organizations_of_recording(user_id: UUID) -> Q:
    member_org_ids = OrganizationUser.filter(user_id=user_id).values('organization_id')
    return Q(recording__organization_id__in=Subquery(member_org_ids))


# Rows below hang off a recording: the tenant scope keeps them inside the caller's organizations; which recordings
# a user sees is decided by LibraryVisibility.recordings (every endpoint starts from it).


class ResultStatus(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'


class RecordingResult(BaseModel):
    """A summary of a recording made by a text model from a template or a custom prompt."""

    recording = fields.ForeignKeyField('models.Recording', related_name='results', on_delete=fields.CASCADE)
    recording_id: UUID
    template = fields.ForeignKeyField(
        'models.SummaryTemplate', related_name='results', on_delete=fields.SET_NULL, null=True
    )
    template_id: UUID | None
    title = fields.CharField(max_length=255)
    # Snapshot: editing the template later does not change existing results.
    prompt = fields.TextField()
    model = fields.CharField(max_length=255)
    status = fields.CharEnumField(ResultStatus, max_length=16, default=ResultStatus.QUEUED)
    content = fields.TextField(default='')
    error_message = fields.CharField(max_length=2000, null=True)
    # null: created automatically after transcription
    created_by = fields.ForeignKeyField(
        'models.User', related_name='recording_results', on_delete=fields.SET_NULL, null=True
    )
    created_by_id: UUID | None

    tenant_scope = Scope(user=_member_organizations_of_recording, organization='recording__organization_id')

    class Meta:
        table = 'recording_result'
        ordering = ('created_at',)


class RecordingProcessing(BaseModel):
    """
    Pipeline bookkeeping per recording, so a re-delivered or retried task never repeats finished steps, and a
    re-transcription collects its segments here while the old transcript stays visible.
    """

    recording = fields.OneToOneField('models.Recording', related_name='processing', on_delete=fields.CASCADE)
    recording_id: UUID
    titled = fields.BooleanField(default=False)
    classified = fields.BooleanField(default=False)
    summarized = fields.BooleanField(default=False)
    # A requested re-transcription: the model and its finished chunks ([{start_ms, end_ms, text}])
    retranscribe_model = fields.CharField(max_length=255, null=True)
    retranscribe_segments: Any = fields.JSONField(default=list)

    tenant_scope = Scope(user=_member_organizations_of_recording, organization='recording__organization_id')

    class Meta:
        table = 'recording_processing'


@post_save(Organization)
async def seed_organization_ai(
    sender: type[Organization],
    instance: Organization,
    created: bool,
    using_db: BaseDBAsyncClient | None,
    update_fields: list[str],
) -> None:
    """A new organization gets its AI settings and the default summary templates in the creating transaction."""
    if not created:
        return
    from app.domains.ai.services.organization_settings_service import OrganizationSettingsService

    await OrganizationSettingsService.ensure(instance, using_db=using_db)
