from typing import Any
from urllib.parse import urlsplit

from loguru import logger
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.services.crypto_service import CryptoService
from app.domains.ai.models import OrganizationSettings, SummaryTemplate
from app.domains.ai.prompts import DEFAULT_SUMMARY_TEMPLATES
from app.domains.ai.schemas import (
    AIConnectionTestResultSchema,
    AIConnectionTestSchema,
    AIOptionsSchema,
    OrganizationSettingsReadSchema,
    OrganizationSettingsUpdateSchema,
)
from app.domains.ai.services.openrouter_client import (
    DEFAULT_BASE_URL,
    AIErrorCode,
    AIProviderError,
    OpenRouterClient,
)
from app.domains.organization.models import Organization


class OrganizationSettingsService:
    @staticmethod
    async def ensure(organization: Organization, using_db: BaseDBAsyncClient | None = None) -> OrganizationSettings:
        """
        The organization's settings, created with defaults on first access. Creating them also seeds the default
        summary templates, so organizations from before this feature get them too (once: deleted templates stay
        deleted).
        """
        settings = await OrganizationSettings.get_or_none(organization_id=organization.id, using_db=using_db)
        if settings is not None:
            return settings
        if using_db is not None:
            # Called inside the transaction that created the organization (post_save hook).
            return await OrganizationSettingsService._create_defaults(organization, using_db)
        try:
            async with in_transaction() as connection:
                return await OrganizationSettingsService._create_defaults(organization, connection)
        except IntegrityError:
            # A concurrent request created them first.
            return await OrganizationSettings.get(organization_id=organization.id)

    @staticmethod
    async def _create_defaults(organization: Organization, db: BaseDBAsyncClient) -> OrganizationSettings:
        settings = await OrganizationSettings.create(organization_id=organization.id, using_db=db)
        if not await SummaryTemplate.filter(organization_id=organization.id).using_db(db).exists():
            for position, template in enumerate(DEFAULT_SUMMARY_TEMPLATES):
                await SummaryTemplate.create(
                    organization_id=organization.id,
                    name=template['name'],
                    prompt=template['prompt'],
                    auto=template['auto'],
                    position=position,
                    using_db=db,
                )
        return settings

    @staticmethod
    def api_key(settings: OrganizationSettings) -> str:
        encrypted = settings.openrouter_api_key_encrypted
        return CryptoService.decrypt(encrypted) if encrypted else ''

    @classmethod
    def build_client(cls, settings: OrganizationSettings, **kwargs: Any) -> OpenRouterClient:
        """Client with the organization's key; raises `AIProviderError(NOT_CONFIGURED)` without one."""
        return OpenRouterClient(settings.openrouter_base_url, cls.api_key(settings), **kwargs)

    @staticmethod
    def to_read(settings: OrganizationSettings) -> OrganizationSettingsReadSchema:
        has_key = bool(settings.openrouter_api_key_encrypted)
        return OrganizationSettingsReadSchema(
            openrouter_base_url=settings.openrouter_base_url,
            has_api_key=has_key,
            api_key_hint=settings.openrouter_api_key_hint or None if has_key else None,
            transcription_models=list(settings.transcription_models or []),
            transcription_default_model=settings.transcription_default_model,
            summary_models=list(settings.summary_models or []),
            summary_default_model=settings.summary_default_model,
            auto_transcribe=settings.auto_transcribe,
            auto_title=settings.auto_title,
            auto_tags=settings.auto_tags,
            auto_project=settings.auto_project,
            segment_seconds=settings.segment_seconds,
            language=settings.language,
            updated_at=settings.updated_at,
        )

    @staticmethod
    def to_options(settings: OrganizationSettings) -> AIOptionsSchema:
        return AIOptionsSchema(
            configured=bool(settings.openrouter_api_key_encrypted and settings.transcription_default_model),
            transcription_models=list(settings.transcription_models or []),
            transcription_default_model=settings.transcription_default_model,
            summary_models=list(settings.summary_models or []),
            summary_default_model=settings.summary_default_model,
        )

    @staticmethod
    def normalize_base_url(value: str) -> str:
        url = value.strip().rstrip('/')
        if not url:
            return DEFAULT_BASE_URL
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            raise AppException.from_attrs(
                ErrorCode.VALIDATION_ERROR, 'Адрес API должен начинаться с http:// или https://'
            )
        if parts.username or parts.password or parts.query or parts.fragment:
            raise AppException.from_attrs(
                ErrorCode.VALIDATION_ERROR, 'Адрес API не должен содержать логин, пароль или параметры'
            )
        return url

    @staticmethod
    def normalize_api_key(value: str | None) -> str:
        key = (value or '').strip()
        if any(char.isspace() for char in key):
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Ключ API не должен содержать пробелы')
        return key

    @staticmethod
    def _models_and_default(
        current_models: list[str],
        current_default: str | None,
        new_models: list[str] | None,
        new_default: str | None,
        default_given: bool,
        label: str,
    ) -> tuple[list[str], str | None]:
        models = list(dict.fromkeys(new_models)) if new_models is not None else list(current_models)
        if default_given:
            if new_default is not None and new_default not in models:
                raise AppException.from_attrs(
                    ErrorCode.VALIDATION_ERROR, f'Модель по умолчанию для {label} должна быть в списке разрешённых'
                )
            return models, new_default
        # The default was not touched: keep it while it is still allowed, otherwise fall back to the first model.
        if current_default in models:
            return models, current_default
        return models, models[0] if models else None

    @classmethod
    async def update(
        cls, settings: OrganizationSettings, data: OrganizationSettingsUpdateSchema
    ) -> OrganizationSettings:
        given = data.model_fields_set
        if 'openrouter_base_url' in given:
            settings.openrouter_base_url = cls.normalize_base_url(data.openrouter_base_url or '')
        if 'openrouter_api_key' in given:
            key = cls.normalize_api_key(data.openrouter_api_key)
            settings.openrouter_api_key_encrypted = CryptoService.encrypt(key) if key else ''
            settings.openrouter_api_key_hint = key[-4:] if len(key) >= 12 else ''
        settings.transcription_models, settings.transcription_default_model = cls._models_and_default(
            settings.transcription_models or [],
            settings.transcription_default_model,
            data.transcription_models,
            data.transcription_default_model,
            'transcription_default_model' in given,
            'расшифровки',
        )
        settings.summary_models, settings.summary_default_model = cls._models_and_default(
            settings.summary_models or [],
            settings.summary_default_model,
            data.summary_models,
            data.summary_default_model,
            'summary_default_model' in given,
            'текста',
        )
        for name in ('auto_transcribe', 'auto_title', 'auto_tags', 'auto_project', 'segment_seconds', 'language'):
            value = getattr(data, name)
            if name in given and value is not None:
                setattr(settings, name, value)
        await settings.save()
        return settings

    @classmethod
    async def test_connection(
        cls, settings: OrganizationSettings, data: AIConnectionTestSchema
    ) -> AIConnectionTestResultSchema:
        """Check a key against the provider; unsaved values from `data` override the saved ones."""
        given = data.model_fields_set
        base_url = (
            cls.normalize_base_url(data.openrouter_base_url or '')
            if 'openrouter_base_url' in given
            else settings.openrouter_base_url
        )
        key = cls.normalize_api_key(data.openrouter_api_key) if 'openrouter_api_key' in given else cls.api_key(settings)
        if not key:
            return AIConnectionTestResultSchema(ok=False, message='Укажите ключ API')
        try:
            async with OpenRouterClient(base_url, key, max_attempts=1) as client:
                await client.check_key()
        except AIProviderError as error:
            logger.info('AI key check failed: {} {}', error.code, error.detail)
            return AIConnectionTestResultSchema(ok=False, message=error.message)
        return AIConnectionTestResultSchema(ok=True, message='Ключ работает')


def ai_error_to_app_exception(error: AIProviderError) -> AppException:
    """Map a provider failure to the API error envelope with the Russian message."""
    code = ErrorCode.RATE_LIMITED if error.code == AIErrorCode.RATE_LIMITED else ErrorCode.APP_ERROR
    return AppException.from_attrs(code, error.message, details={'ai_error': str(error.code)})
