from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi_ronin.decorators import action, viewset
from fastapi_ronin.mixins import DestroyMixin
from fastapi_ronin.permissions import BasePermission, IsAuthenticated
from fastapi_ronin.types import PydanticModel
from tortoise.expressions import Subquery
from tortoise.queryset import QuerySet

from app.core.auth import get_current_auth_state
from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.viewsets import BaseGenericViewSet, BaseModelViewSet, BaseReadOnlyViewSet
from app.domains.ai.filters import RecordingResultFilterSet, SummaryTemplateFilterSet
from app.domains.ai.models import OrganizationSettings, RecordingResult, SummaryTemplate
from app.domains.ai.schemas import (
    AIConnectionTestResultSchema,
    AIConnectionTestSchema,
    AIModelKind,
    AIModelSchema,
    AIOptionsSchema,
    OrganizationSettingsReadSchema,
    OrganizationSettingsUpdateSchema,
    RecordingResultReadSchema,
    RecordingResultsCreateSchema,
    RetranscribeSchema,
    SummaryTemplateCreateSchema,
    SummaryTemplateReadSchema,
    SummaryTemplateUpdateSchema,
)
from app.domains.ai.services.model_catalog_service import ModelCatalogService
from app.domains.ai.services.openrouter_client import AIProviderError
from app.domains.ai.services.organization_settings_service import (
    OrganizationSettingsService,
    ai_error_to_app_exception,
)
from app.domains.ai.services.processing_request_service import ProcessingRequestService
from app.domains.ai.services.result_service import ResultService
from app.domains.ai.services.summary_template_service import SummaryTemplateService
from app.domains.library.models import Recording
from app.domains.library.schemas import RecordingDetailSchema
from app.domains.library.services.pipeline import RecordingPipeline
from app.domains.library.services.recording_presenter import RecordingPresenter
from app.domains.library.services.visibility import LibraryVisibility
from app.domains.organization.models import Organization
from app.domains.user.models import User
from app.shared.permissions.is_organization_admin import IsOrganizationAdmin
from app.shared.services.filter_objects_manager import FilterObjectsManager

ai_settings_router = APIRouter(prefix='/ai-settings', tags=['ai-settings'])
summary_templates_router = APIRouter(prefix='/summary-templates', tags=['summary-templates'])
# AI actions on one recording live under /recordings next to the library's routes (docs/pipeline-seam.md).
recording_ai_router = APIRouter(prefix='/recordings', tags=['recording-ai'])
recording_results_router = APIRouter(prefix='/recording-results', tags=['recording-results'])
routers = (ai_settings_router, summary_templates_router, recording_ai_router, recording_results_router)

# Public share links expose finished results through the library's seam.
RecordingPipeline.register_share_results_provider(ResultService.shared_results)
RecordingPipeline.register_result_ids_checker(ResultService.result_ids_of)


def _visible_recordings(user: User) -> QuerySet[Recording]:
    queryset = LibraryVisibility.recordings(user, _current_organization().id)
    return FilterObjectsManager.filter(queryset, get_current_auth_state())


def _current_organization() -> Organization:
    organization = get_current_auth_state().organization
    if organization is None:
        raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Organization-Key header is required')
    return organization


@viewset(ai_settings_router)
class AISettingsViewSet(BaseGenericViewSet[OrganizationSettings]):
    """The organization's AI settings (one per organization, from `Organization-Key`). Org admins only, except
    `options`, which every member reads for the model pickers."""

    model = OrganizationSettings
    read_schema = OrganizationSettingsReadSchema

    async def get_permissions(self) -> list[BasePermission]:
        if self.action == 'options':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsOrganizationAdmin()]

    async def _settings(self) -> OrganizationSettings:
        return await OrganizationSettingsService.ensure(_current_organization())

    @action(methods=['GET'])
    async def current(self) -> OrganizationSettingsReadSchema:
        """AI settings; the API key is never returned (`has_api_key`, `api_key_hint`)."""
        return OrganizationSettingsService.to_read(await self._settings())

    @action(methods=['PATCH'], path='current')
    async def update_current(self, data: OrganizationSettingsUpdateSchema) -> OrganizationSettingsReadSchema:
        """Change AI settings; default models must be in the allowed lists."""
        settings = await OrganizationSettingsService.update(await self._settings(), data)
        return OrganizationSettingsService.to_read(settings)

    @action(methods=['POST'], path='test')
    async def test_connection(self, data: AIConnectionTestSchema) -> AIConnectionTestResultSchema:
        """Check the saved key (or unsaved `openrouter_base_url` / `openrouter_api_key`) against the provider."""
        return await OrganizationSettingsService.test_connection(await self._settings(), data)

    @action(methods=['GET'])
    async def models(
        self,
        kind: Annotated[AIModelKind, Query()] = AIModelKind.AUDIO,
        search: Annotated[str | None, Query(max_length=100)] = None,
    ) -> list[AIModelSchema]:
        """Provider model catalog for the pickers (cached): `audio` = audio-input models, `text` = text models."""
        try:
            return await ModelCatalogService.list_models(await self._settings(), kind, search)
        except AIProviderError as error:
            raise ai_error_to_app_exception(error) from error

    @action(methods=['GET'])
    async def options(self) -> AIOptionsSchema:
        """Allowed models and defaults for members; no secrets."""
        return OrganizationSettingsService.to_options(await self._settings())


@viewset(summary_templates_router)
class SummaryTemplateViewSet(BaseModelViewSet[SummaryTemplate]):
    """Summary templates: every member reads them, org admins manage them."""

    model = SummaryTemplate
    read_schema = SummaryTemplateReadSchema
    create_schema = SummaryTemplateCreateSchema
    update_schema = SummaryTemplateUpdateSchema
    filterset_class = SummaryTemplateFilterSet

    async def get_permissions(self) -> list[BasePermission]:
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsOrganizationAdmin()]

    async def get_queryset(self):
        if self.action == 'list':
            # Organizations created before templates existed get the defaults on first look.
            await OrganizationSettingsService.ensure(_current_organization())
        return await super().get_queryset()

    async def validate_data(self, data: PydanticModel) -> PydanticModel | dict[str, Any]:
        # An explicit null in a PATCH means "unchanged", never "clear".
        return data.model_dump(exclude_unset=True, exclude_none=True)

    async def perform_create(self, obj: SummaryTemplate) -> SummaryTemplate:
        data = self.state.validated_data
        append = not (isinstance(data, dict) and 'position' in data)
        return await SummaryTemplateService.create(obj, self.user, append=append)


@viewset(recording_ai_router)
class RecordingAIViewSet(BaseGenericViewSet[Recording]):
    """Summaries and processing requests of one recording; whoever sees the recording may use them."""

    model = Recording
    read_schema = RecordingDetailSchema

    async def get_queryset(self):
        return _visible_recordings(self.user)

    @action(methods=['GET'], detail=True)
    async def results(self, item_id: UUID) -> list[RecordingResultReadSchema]:
        """Summaries of the recording, oldest first."""
        recording = await self.get_object(item_id)
        results = await RecordingResult.filter(recording_id=recording.id).order_by('created_at', 'id')
        return [await RecordingResultReadSchema.from_tortoise_orm(result) for result in results]

    @action(methods=['POST'], detail=True, path='results', status_code=201)
    async def create_results(
        self, item_id: UUID, data: RecordingResultsCreateSchema
    ) -> list[RecordingResultReadSchema]:
        """Request summaries: one per template plus one for `custom_prompt`; each is generated by its own task."""
        request = await ResultService.validate_create(await self.get_object(item_id), data)
        results = await ResultService.create(request, self.user)
        return [await RecordingResultReadSchema.from_tortoise_orm(result) for result in results]

    @action(methods=['POST'], detail=True)
    async def retry(self, item_id: UUID) -> RecordingDetailSchema:
        """«Повторить»: resume failed (or not started) processing from the last finished chunk."""
        recording = await ProcessingRequestService.retry(await self.get_object(item_id))
        return await RecordingPresenter.detail(recording, self.user)

    @action(methods=['POST'], detail=True)
    async def retranscribe(self, item_id: UUID, data: RetranscribeSchema) -> RecordingDetailSchema:
        """Transcribe again with an allowed model; the current transcript stays until the new one is complete."""
        recording = await self.get_object(item_id)
        model = await ProcessingRequestService.validate_retranscribe(recording, data)
        recording = await ProcessingRequestService.retranscribe(recording, model)
        return await RecordingPresenter.detail(recording, self.user)


@viewset(recording_results_router)
class RecordingResultViewSet(BaseReadOnlyViewSet[RecordingResult], DestroyMixin[RecordingResult]):
    """
    Results of the recordings the caller sees: `?recording_id=` for one recording, `?updated_after=` for an
    incremental refresh after /recordings/sync reported changed recordings.
    """

    model = RecordingResult
    read_schema = RecordingResultReadSchema
    filterset_class = RecordingResultFilterSet

    async def get_queryset(self):
        queryset = await super().get_queryset()
        return queryset.filter(recording_id__in=Subquery(_visible_recordings(self.user).values('id')))

    async def perform_destroy(self, obj: RecordingResult) -> None:
        """Own results; automatic ones also by the recording's author; any by an org admin."""
        await ResultService.delete(obj, self.user)

    @action(methods=['POST'], detail=True, status_code=201)
    async def regenerate(self, item_id: UUID) -> RecordingResultReadSchema:
        """A new result with the same prompt and model; the old one stays."""
        result = await ResultService.regenerate(await self.get_object(item_id), self.user)
        return await RecordingResultReadSchema.from_tortoise_orm(result)
