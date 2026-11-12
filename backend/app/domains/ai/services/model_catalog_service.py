import hashlib
import json
import time
from typing import Any, ClassVar

from loguru import logger

from app.core.redis import get_redis
from app.core.settings import settings as app_settings
from app.domains.ai.models import OrganizationSettings
from app.domains.ai.schemas import AIModelKind, AIModelSchema
from app.domains.ai.services.openrouter_client import OpenRouterClient
from app.domains.ai.services.organization_settings_service import OrganizationSettingsService
from app.domains.ai.services.transcription_engine import TranscriptionMode

MAX_RESULTS = 300


def _modalities(item: dict[str, Any], key: str) -> list[str]:
    architecture = item.get('architecture')
    values = architecture.get(key) if isinstance(architecture, dict) else None
    return [str(value) for value in values] if isinstance(values, list) else []


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class ModelCatalogService:
    """
    The provider's model catalog, normalized and cached per base URL + key (Redis, process memory in tests or when
    Redis is down) for `AI_MODELS_CACHE_SECONDS`. Audio models are those with `audio` in `input_modalities`, like the
    desktop app; dedicated speech-to-text models only appear in the `output_modalities=transcription` listing.
    """

    _memory: ClassVar[dict[str, tuple[float, list[dict[str, Any]]]]] = {}

    @classmethod
    async def list_models(
        cls, settings: OrganizationSettings, kind: AIModelKind, search: str | None = None
    ) -> list[AIModelSchema]:
        catalog = await cls.catalog(settings)
        query = (search or '').strip().casefold()
        result = []
        for item in catalog:
            if not cls.matches_kind(item, kind):
                continue
            if query and query not in item['id'].casefold() and query not in item['name'].casefold():
                continue
            result.append(AIModelSchema(**item))
        result.sort(key=lambda model: model.name.casefold())
        return result[:MAX_RESULTS]

    @classmethod
    async def transcription_mode(cls, settings: OrganizationSettings, model_id: str) -> TranscriptionMode:
        """`/audio/transcriptions` for models that only output transcriptions, chat with `input_audio` otherwise."""
        try:
            catalog = await cls.catalog(settings)
        except Exception as e:
            logger.warning('Model catalog unavailable, assuming chat transcription for {}: {}', model_id, e)
            return TranscriptionMode.CHAT
        item = next((item for item in catalog if item['id'] == model_id), None)
        if item and 'transcription' in item['output_modalities'] and 'text' not in item['output_modalities']:
            return TranscriptionMode.TRANSCRIPTION
        return TranscriptionMode.CHAT

    @staticmethod
    def matches_kind(item: dict[str, Any], kind: AIModelKind) -> bool:
        inputs, outputs = item['input_modalities'], item['output_modalities']
        if kind == AIModelKind.AUDIO:
            return 'audio' in inputs and ('text' in outputs or 'transcription' in outputs)
        return 'text' in inputs and 'text' in outputs and 'transcription' not in outputs

    @classmethod
    async def catalog(cls, settings: OrganizationSettings) -> list[dict[str, Any]]:
        api_key = OrganizationSettingsService.api_key(settings)
        cache_key = cls._cache_key(settings.openrouter_base_url, api_key)
        cached = await cls._cache_get(cache_key)
        if cached is not None:
            return cached
        async with OrganizationSettingsService.build_client(settings, max_attempts=2) as client:
            catalog = await cls._fetch(client)
        await cls._cache_set(cache_key, catalog)
        return catalog

    @classmethod
    async def _fetch(cls, client: OpenRouterClient) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for output in (None, 'transcription'):
            try:
                items = await client.list_models(output_modalities=output)
            except Exception:
                if output is None:
                    raise
                # Not every compatible API supports the modality filter.
                continue
            for raw in items:
                item = cls._normalize(raw)
                if item is None:
                    continue
                if existing := merged.get(item['id']):
                    for key in ('input_modalities', 'output_modalities'):
                        existing[key] = list(dict.fromkeys([*existing[key], *item[key]]))
                else:
                    merged[item['id']] = item
        return list(merged.values())

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
        model_id = raw.get('id')
        if not isinstance(model_id, str) or not model_id.strip():
            return None
        top_provider = raw.get('top_provider')
        if not isinstance(top_provider, dict):
            top_provider = {}
        pricing = raw.get('pricing')
        if not isinstance(pricing, dict):
            pricing = {}
        name = raw.get('name')
        return {
            'id': model_id,
            'name': name if isinstance(name, str) and name.strip() else model_id,
            'context_length': _int_or_none(raw.get('context_length')),
            'max_completion_tokens': _int_or_none(top_provider.get('max_completion_tokens')),
            'input_modalities': _modalities(raw, 'input_modalities'),
            'output_modalities': _modalities(raw, 'output_modalities'),
            'prompt_price': str(pricing['prompt']) if pricing.get('prompt') is not None else None,
            'completion_price': str(pricing['completion']) if pricing.get('completion') is not None else None,
        }

    # ----- cache -----

    @staticmethod
    def _cache_key(base_url: str, api_key: str) -> str:
        digest = hashlib.sha256(f'{base_url}|{api_key}'.encode()).hexdigest()
        return f'ai:models:{digest}'

    @staticmethod
    def _use_redis() -> bool:
        return not app_settings.testing

    @classmethod
    async def _cache_get(cls, key: str) -> list[dict[str, Any]] | None:
        if cls._use_redis():
            try:
                raw = await get_redis().get(key)
                if raw:
                    return json.loads(raw)
                return None
            except Exception as e:
                logger.warning('Model catalog cache falls back to memory: {}', e)
        entry = cls._memory.get(key)
        if entry and entry[0] > time.monotonic():
            return entry[1]
        return None

    @classmethod
    async def _cache_set(cls, key: str, catalog: list[dict[str, Any]]) -> None:
        ttl = app_settings.ai_models_cache_seconds
        if cls._use_redis():
            try:
                await get_redis().set(key, json.dumps(catalog), ex=ttl)
                return
            except Exception as e:
                logger.warning('Model catalog cache falls back to memory: {}', e)
        cls._memory[key] = (time.monotonic() + ttl, catalog)

    @classmethod
    def clear_memory_cache(cls) -> None:
        cls._memory.clear()
