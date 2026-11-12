from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi_ronin.decorators import action, viewset
from fastapi_ronin.permissions import BasePermission, IsAuthenticated
from fastapi_ronin.types import PydanticModel

from app.core.auth import get_current_auth_state
from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.viewsets import BaseGenericViewSet, BaseModelViewSet
from app.domains.ai.filters import SummaryTemplateFilterSet
from app.domains.ai.models import OrganizationSettings, SummaryTemplate
from app.domains.ai.schemas import (
    AIConnectionTestResultSchema,
    AIConnectionTestSchema,
    AIModelKind,
    AIModelSchema,
    AIOptionsSchema,
    OrganizationSettingsReadSchema,
    OrganizationSettingsUpdateSchema,
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
from app.domains.ai.services.summary_template_service import SummaryTemplateService
from app.domains.organization.models import Organization
from app.shared.permissions.is_organization_admin import IsOrganizationAdmin

ai_settings_router = APIRouter(prefix='/ai-settings', tags=['ai-settings'])
summary_templates_router = APIRouter(prefix='/summary-templates', tags=['summary-templates'])
routers = (ai_settings_router, summary_templates_router)


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
