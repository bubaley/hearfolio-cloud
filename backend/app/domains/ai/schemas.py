from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi_ronin.decorators import schema
from pydantic import ConfigDict, Field, StringConstraints

from app.core.models import BaseCreateSchema, BaseReadSchema, BaseSchema
from app.domains.ai.models import (
    MAX_SEGMENT_SECONDS,
    MIN_SEGMENT_SECONDS,
    RecordingResult,
    ResultStatus,
    SummaryTemplate,
)

ModelId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255, pattern=r'^\S+$')]
LanguageCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r'^(auto|[a-z]{2,3}(-[A-Za-z]{2,4})?)$')]

# ORGANIZATION_SETTINGS_SCHEMAS


class OrganizationSettingsReadSchema(BaseSchema):
    """AI settings as org admins see them; the API key itself is never returned."""

    openrouter_base_url: str
    has_api_key: bool
    api_key_hint: str | None
    transcription_models: list[str]
    transcription_default_model: str | None
    summary_models: list[str]
    summary_default_model: str | None
    auto_transcribe: bool
    auto_title: bool
    auto_tags: bool
    auto_project: bool
    segment_seconds: int
    language: str
    updated_at: datetime


class OrganizationSettingsUpdateSchema(BaseSchema):
    """Partial update. `openrouter_api_key`: omitted keeps the key, `""` or null removes it, a value replaces it."""

    openrouter_base_url: str | None = Field(None, max_length=512)
    openrouter_api_key: str | None = Field(None, max_length=512)
    transcription_models: list[ModelId] | None = Field(None, max_length=50)
    transcription_default_model: ModelId | None = None
    summary_models: list[ModelId] | None = Field(None, max_length=50)
    summary_default_model: ModelId | None = None
    auto_transcribe: bool | None = None
    auto_title: bool | None = None
    auto_tags: bool | None = None
    auto_project: bool | None = None
    segment_seconds: int | None = Field(None, ge=MIN_SEGMENT_SECONDS, le=MAX_SEGMENT_SECONDS)
    language: LanguageCode | None = None

    model_config = ConfigDict(extra='forbid')


class AIConnectionTestSchema(BaseSchema):
    """Values to check before saving them; omitted fields use the saved settings."""

    openrouter_base_url: str | None = Field(None, max_length=512)
    openrouter_api_key: str | None = Field(None, max_length=512)

    model_config = ConfigDict(extra='forbid')


class AIConnectionTestResultSchema(BaseSchema):
    ok: bool
    message: str


class AIModelKind(StrEnum):
    AUDIO = 'audio'
    TEXT = 'text'


class AIModelSchema(BaseSchema):
    id: str
    name: str
    context_length: int | None = None
    max_completion_tokens: int | None = None
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    # USD per token as reported by the provider
    prompt_price: str | None = None
    completion_price: str | None = None


class AIOptionsSchema(BaseSchema):
    """What members may choose; no secrets."""

    configured: bool
    transcription_models: list[str]
    transcription_default_model: str | None
    summary_models: list[str]
    summary_default_model: str | None
    # The automation switches, so clients can say what happens after an upload
    auto_transcribe: bool
    auto_title: bool
    auto_tags: bool
    auto_project: bool


# SUMMARY_TEMPLATE_SCHEMAS


@schema(model=SummaryTemplate)
class SummaryTemplateCreateSchema(BaseCreateSchema):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
    # One line for pickers; clients fall back to the prompt's first sentence when it is empty
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ''
    auto: bool = False
    position: int | None = Field(None, ge=0)


@schema(model=SummaryTemplate)
class SummaryTemplateUpdateSchema(BaseCreateSchema):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    auto: bool | None = None
    position: int | None = Field(None, ge=0)

    model_config = ConfigDict(extra='forbid')


@schema(model=SummaryTemplate)
class SummaryTemplateReadSchema(BaseReadSchema):
    name: str
    prompt: str
    description: str
    auto: bool
    position: int
    created_by_id: UUID | None


# RECORDING_RESULT_SCHEMAS


@schema(model=RecordingResult)
class RecordingResultReadSchema(BaseReadSchema):
    recording_id: UUID
    template_id: UUID | None
    title: str
    prompt: str
    model: str
    status: ResultStatus
    content: str
    # Stable machine code (AIErrorCode); `error_message` is the Russian fallback
    error_code: str | None
    error_message: str | None
    created_by_id: UUID | None


class RecordingResultsCreateSchema(BaseSchema):
    """Summaries to make: one per template plus one for `custom_prompt`; `model` defaults to the organization's."""

    template_ids: list[UUID] = Field(default_factory=list, max_length=20)
    custom_prompt: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)] | None = None
    model: ModelId | None = None

    model_config = ConfigDict(extra='forbid')


class RetranscribeSchema(BaseSchema):
    """`model` must be an allowed transcription model; omitted means the organization's default."""

    model: ModelId | None = None

    model_config = ConfigDict(extra='forbid')
