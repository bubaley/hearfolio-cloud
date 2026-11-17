import asyncio
import base64
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, ClassVar, Self

import httpx2
from loguru import logger

from app.domains.ai.utils.transcript_phrases import TimedSegment, TimedWord, parse_segments, parse_words

DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1'
APP_TITLE = 'Hearfolio Cloud'
APP_REFERER = 'https://hearfolio.app'
# Responses beyond this are not a chat completion or a catalog; refuse to parse them.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class AIErrorCode(StrEnum):
    NOT_CONFIGURED = 'not_configured'
    AUTH = 'auth'
    PAYMENT = 'payment'
    FORBIDDEN = 'forbidden'
    RATE_LIMITED = 'rate_limited'
    BAD_REQUEST = 'bad_request'
    MODEL_UNAVAILABLE = 'model_unavailable'
    TOO_LARGE = 'too_large'
    SERVER = 'server'
    NETWORK = 'network'
    TIMEOUT = 'timeout'
    INVALID_RESPONSE = 'invalid_response'
    INCOMPLETE = 'incomplete'
    EMPTY = 'empty'
    CONTENT_FILTER = 'content_filter'
    # Pipeline failures outside the provider (Recording.error_code / RecordingResult.error_code)
    STORAGE = 'storage'
    AUDIO = 'audio'
    INTERNAL = 'internal'


ERROR_MESSAGES: dict[AIErrorCode, str] = {
    AIErrorCode.NOT_CONFIGURED: 'AI не настроен: укажите ключ OpenRouter и модели в настройках организации',
    AIErrorCode.AUTH: 'Ключ OpenRouter не принят: проверьте его в настройках AI',
    AIErrorCode.PAYMENT: 'На счёте OpenRouter недостаточно средств',
    AIErrorCode.FORBIDDEN: 'OpenRouter отклонил запрос: у ключа нет доступа к этой модели',
    AIErrorCode.RATE_LIMITED: 'OpenRouter ограничил частоту запросов, попробуйте позже',
    AIErrorCode.BAD_REQUEST: 'OpenRouter не принял запрос: проверьте выбранную модель',
    AIErrorCode.MODEL_UNAVAILABLE: 'Модель недоступна у провайдера, выберите другую',
    AIErrorCode.TOO_LARGE: 'Фрагмент слишком большой для модели, уменьшите длину сегмента',
    AIErrorCode.SERVER: 'Сервис модели временно недоступен, попробуйте позже',
    AIErrorCode.NETWORK: 'Не удалось связаться с OpenRouter',
    AIErrorCode.TIMEOUT: 'OpenRouter не ответил вовремя',
    AIErrorCode.INVALID_RESPONSE: 'OpenRouter вернул непонятный ответ',
    AIErrorCode.INCOMPLETE: 'Модель вернула только часть текста',
    AIErrorCode.EMPTY: 'Модель вернула пустой ответ — повторите или выберите другую модель в «AI и модели»',
    AIErrorCode.CONTENT_FILTER: 'Провайдер модели отказался обрабатывать этот фрагмент',
    AIErrorCode.STORAGE: 'Не удалось получить аудио из хранилища',
    AIErrorCode.AUDIO: 'Не удалось прочитать аудиофайл',
    AIErrorCode.INTERNAL: 'Не удалось обработать запись, попробуйте ещё раз',
}

RETRYABLE_CODES = frozenset(
    {
        AIErrorCode.RATE_LIMITED,
        AIErrorCode.SERVER,
        AIErrorCode.NETWORK,
        AIErrorCode.TIMEOUT,
        AIErrorCode.INVALID_RESPONSE,
        AIErrorCode.INCOMPLETE,
        AIErrorCode.EMPTY,
    }
)


class AIProviderError(Exception):
    """A provider failure with a stable code and a Russian message safe to show users (never raw provider JSON)."""

    def __init__(
        self,
        code: AIErrorCode,
        message: str | None = None,
        *,
        status_code: int | None = None,
        detail: str = '',
        retry_after: float | None = None,
    ):
        self.code = code
        self.message = message or ERROR_MESSAGES[code]
        self.status_code = status_code
        # Redacted provider text for logs only.
        self.detail = detail
        self.retry_after = retry_after
        super().__init__(self.message)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES


@dataclass
class ChatResult:
    text: str
    finish_reason: str | None
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class TranscriptionResult(ChatResult):
    """A `/audio/transcriptions` answer: text plus whatever timing the model returned (times relative to the audio)."""

    words: list[TimedWord] = field(default_factory=list)
    segments: list[TimedSegment] = field(default_factory=list)


class TranscriptionRequest(IntEnum):
    """How much structure a `/audio/transcriptions` request asks for; a provider that rejects one gets the next."""

    # verbose_json with segment + word timestamps and the model author's diarization options (if known)
    DIARIZED = 0
    # verbose_json with timestamps, no provider options
    TIMED = 1
    # the plain request (`text` only), as before timestamps were asked for
    PLAIN = 2


# Diarization flags by model author (the part of the model id before `/`), sent as `provider.options`. Only xAI is
# verified live; Deepgram and Azure follow the OpenRouter docs. Mirrored by the app.
DIARIZATION_OPTIONS: dict[str, dict[str, Any]] = {
    'x-ai': {'xai': {'diarize': True}},
    'deepgram': {'deepgram': {'diarize': True}},
    'azure': {'azure': {'diarization': {'enabled': True}}},
    'microsoft': {'azure': {'diarization': {'enabled': True}}},
}


def diarization_options(model: str) -> dict[str, Any] | None:
    return DIARIZATION_OPTIONS.get(model.split('/', 1)[0].casefold())


Sleep = Callable[[float], Awaitable[None]]
# Called with (model, provider `usage` object) for every billed answer: chat completions and transcriptions.
OnUsage = Callable[[str, dict[str, Any]], Awaitable[None]]


class OpenRouterClient:
    """
    Async client for an OpenRouter/OpenAI-compatible API: model catalog, key check, chat completions (text, JSON,
    `input_audio`) and `/audio/transcriptions`. Transport failures (429, 5xx, network, timeouts) are retried with
    exponential backoff; content failures (`finish_reason=length`, empty text) are raised for the caller to decide.
    """

    # Used when no transport is passed; tests install an `httpx2.MockTransport` here.
    default_transport: ClassVar[httpx2.AsyncBaseTransport | None] = None
    # (base URL, model) -> the richest transcription request it accepted after rejecting a richer one. Process memory:
    # a new worker pays at most two rejected (free) requests per model again.
    transcription_levels: ClassVar[dict[tuple[str, str], TranscriptionRequest]] = {}

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 30.0,
        sleep: Sleep = asyncio.sleep,
        on_usage: OnUsage | None = None,
    ):
        if not api_key:
            raise AIProviderError(AIErrorCode.NOT_CONFIGURED)
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip('/')
        self._api_key = api_key
        self.max_attempts = max(1, max_attempts)
        self.backoff_seconds = backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._sleep = sleep
        self.on_usage = on_usage
        self._http = httpx2.AsyncClient(
            transport=transport or self.default_transport,
            timeout=httpx2.Timeout(60.0, connect=15.0),
            headers={
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': APP_REFERER,
                'X-Title': APP_TITLE,
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ----- public API -----

    async def list_models(self, *, output_modalities: str | None = None) -> list[dict[str, Any]]:
        params = {'output_modalities': output_modalities} if output_modalities else None
        payload = await self._request('GET', '/models', params=params, timeout=30.0)
        data = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise AIProviderError(AIErrorCode.INVALID_RESPONSE, detail='models: no data list')
        return [item for item in data if isinstance(item, dict)]

    async def check_key(self) -> None:
        """Raise `AIProviderError` unless the key is accepted. `/key` is OpenRouter-specific; fall back to `/models`."""
        try:
            await self._request('GET', '/key', timeout=20.0, attempts=1)
        except AIProviderError as error:
            if error.status_code not in (404, 405):
                raise
            await self._request('GET', '/models', timeout=30.0, attempts=1)

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        json_mode: bool = False,
        reasoning: dict[str, Any] | None = None,
        timeout: float = 120.0,
    ) -> ChatResult:
        body: dict[str, Any] = {'model': model, 'messages': messages, 'stream': False}
        if reasoning is not None:
            body['reasoning'] = reasoning
        if max_tokens:
            body['max_tokens'] = max_tokens
        if temperature is not None:
            body['temperature'] = temperature
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        payload = await self._request('POST', '/chat/completions', json_body=body, timeout=timeout)
        return self._parse_chat(payload)

    async def chat_audio(
        self,
        *,
        model: str,
        prompt: str,
        audio: bytes,
        audio_format: str,
        system: str | None = None,
        max_tokens: int,
        timeout: float,
    ) -> ChatResult:
        """Chat completion with one `input_audio` part (base64) after the text instruction."""
        content = [
            {'type': 'text', 'text': prompt},
            {
                'type': 'input_audio',
                'input_audio': {'data': base64.b64encode(audio).decode('ascii'), 'format': audio_format},
            },
        ]
        messages: list[dict[str, Any]] = [{'role': 'system', 'content': system}] if system else []
        messages.append({'role': 'user', 'content': content})
        return await self.chat(model=model, messages=messages, max_tokens=max_tokens, temperature=0, timeout=timeout)

    async def transcribe(
        self, *, model: str, audio: bytes, audio_format: str, language: str | None, timeout: float
    ) -> TranscriptionResult:
        """
        Dedicated speech-to-text models (`output_modalities=transcription`) through `/audio/transcriptions`. Asks for
        word timestamps and speakers first; a model that rejects the request as unsupported (HTTP 400, not a
        transient or size error) gets the next simpler request, and the accepted level is remembered per model.
        """
        key = (self.base_url, model)
        options = diarization_options(model)
        first = TranscriptionRequest.DIARIZED if options else TranscriptionRequest.TIMED
        level = self.transcription_levels.get(key, first)
        data = base64.b64encode(audio).decode('ascii')
        while True:
            body = self._transcription_body(level, model=model, data=data, audio_format=audio_format, language=language)
            if level == TranscriptionRequest.DIARIZED and options:
                body['provider'] = {'options': options}
            try:
                payload = await self._request('POST', '/audio/transcriptions', json_body=body, timeout=timeout)
            except AIProviderError as error:
                if level == TranscriptionRequest.PLAIN or not self._unsupported(error):
                    raise
                logger.info('Model {} rejected the {} transcription request: {}', model, level.name, error.detail)
                level = TranscriptionRequest(level + 1)
                continue
            result = self._parse_transcription(payload, model)
            if level != self.transcription_levels.get(key, first):
                self.transcription_levels[key] = level
            return result

    @staticmethod
    def _transcription_body(
        level: TranscriptionRequest, *, model: str, data: str, audio_format: str, language: str | None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {'model': model, 'input_audio': {'data': data, 'format': audio_format}}
        if language:
            body['language'] = language
        if level <= TranscriptionRequest.TIMED:
            body['response_format'] = 'verbose_json'
            body['timestamp_granularities'] = ['segment', 'word']
        return body

    @staticmethod
    def _unsupported(error: AIProviderError) -> bool:
        """A request the provider refuses by shape (unknown parameter, unsupported format), not by load or size."""
        if error.code == AIErrorCode.BAD_REQUEST and error.status_code in (400, 422):
            return True
        return error.status_code == 404 and 'parameter' in error.detail.lower()

    @staticmethod
    def _parse_transcription(payload: Any, model: str) -> TranscriptionResult:
        text = payload.get('text') if isinstance(payload, dict) else None
        if not isinstance(text, str):
            raise AIProviderError(AIErrorCode.INVALID_RESPONSE, detail='transcription: no text')
        usage = payload.get('usage')
        return TranscriptionResult(
            text=text,
            finish_reason='stop',
            model=model,
            usage=usage if isinstance(usage, dict) else {},
            words=parse_words(payload.get('words')),
            segments=parse_segments(payload.get('segments')),
        )

    # ----- transport -----

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float,
        attempts: int | None = None,
    ) -> Any:
        attempts = attempts or self.max_attempts
        for attempt in range(1, attempts + 1):
            try:
                return await self._send(method, path, params=params, json_body=json_body, timeout=timeout)
            except AIProviderError as error:
                if not error.retryable or error.code in (AIErrorCode.INCOMPLETE, AIErrorCode.EMPTY):
                    raise
                if attempt >= attempts:
                    raise
                delay = self._backoff(attempt, error.retry_after)
                logger.warning(
                    'AI provider {} {} failed ({}), retry {}/{} in {:.1f}s: {}',
                    method,
                    path,
                    error.code,
                    attempt,
                    attempts - 1,
                    delay,
                    error.detail,
                )
                await self._sleep(delay)
        raise AssertionError('unreachable')

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(max(retry_after, 0.0), self.max_backoff_seconds)
        base = self.backoff_seconds * (2 ** (attempt - 1))
        return min(base + random.uniform(0, base / 2), self.max_backoff_seconds)  # nosec B311 - retry jitter, not crypto

    async def _send(
        self, method: str, path: str, *, params: dict[str, str] | None, json_body: dict[str, Any] | None, timeout: float
    ) -> Any:
        try:
            response = await self._http.request(
                method,
                f'{self.base_url}{path}',
                params=params,
                json=json_body,
                timeout=httpx2.Timeout(timeout, connect=15.0),
            )
        except httpx2.TimeoutException as e:
            raise AIProviderError(AIErrorCode.TIMEOUT, detail=type(e).__name__) from e
        except httpx2.TransportError as e:
            raise AIProviderError(AIErrorCode.NETWORK, detail=self._redact(str(e))) from e

        body = response.content[:MAX_RESPONSE_BYTES]
        if response.status_code >= 400:
            raise self._http_error(response.status_code, body, response.headers.get('retry-after'))
        try:
            payload = json.loads(body)
        except ValueError as e:
            raise AIProviderError(AIErrorCode.INVALID_RESPONSE, detail='non-JSON body') from e
        # Billed even when the answer then turns out empty, cut off or an upstream error.
        await self._report_usage(json_body, payload)
        if isinstance(payload, dict) and payload.get('error'):
            # OpenRouter reports upstream provider failures as 200 with an `error` object.
            error = payload['error']
            code = error.get('code') if isinstance(error, dict) else None
            status = code if isinstance(code, int) else 502
            raise self._http_error(status, json.dumps(payload).encode(), None)
        return payload

    async def _report_usage(self, json_body: dict[str, Any] | None, payload: Any) -> None:
        """Hand the provider's own measurements to `on_usage`; accounting never breaks a request."""
        usage = payload.get('usage') if isinstance(payload, dict) else None
        if self.on_usage is None or not isinstance(usage, dict) or not json_body:
            return
        try:
            await self.on_usage(str(payload.get('model') or json_body.get('model') or ''), usage)
        except Exception:
            logger.exception('Could not record AI usage')

    def _http_error(self, status: int, body: bytes, retry_after: str | None) -> AIProviderError:
        detail = self._redact(self._error_text(body))
        lowered = detail.lower()
        if status == 401:
            code = AIErrorCode.AUTH
        elif status == 402:
            code = AIErrorCode.PAYMENT
        elif status == 403:
            code = (
                AIErrorCode.CONTENT_FILTER if 'moderation' in lowered or 'flagged' in lowered else AIErrorCode.FORBIDDEN
            )
        elif status == 404:
            code = AIErrorCode.MODEL_UNAVAILABLE
        elif status == 408:
            code = AIErrorCode.TIMEOUT
        elif status == 413:
            code = AIErrorCode.TOO_LARGE
        elif status == 429:
            code = AIErrorCode.RATE_LIMITED
        elif status >= 500:
            code = AIErrorCode.SERVER
        elif any(marker in lowered for marker in ('context length', 'too long', 'too large', 'large audio')):
            code = AIErrorCode.TOO_LARGE
        elif 'no endpoints' in lowered or 'not a valid model' in lowered or 'model not found' in lowered:
            code = AIErrorCode.MODEL_UNAVAILABLE
        else:
            code = AIErrorCode.BAD_REQUEST
        return AIProviderError(
            code, status_code=status, detail=f'HTTP {status}: {detail}', retry_after=self._retry_after(retry_after)
        )

    @staticmethod
    def _retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _error_text(body: bytes) -> str:
        try:
            payload = json.loads(body)
        except ValueError:
            return body[:300].decode('utf-8', 'replace')
        error = payload.get('error') if isinstance(payload, dict) else None
        if isinstance(error, dict):
            parts = [str(error.get('message') or '')]
            metadata = error.get('metadata')
            if isinstance(metadata, dict) and metadata.get('raw'):
                parts.append(str(metadata['raw']))
            return ' | '.join(part for part in parts if part)[:500]
        return str(error or payload)[:300]

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, '[redacted]') if self._api_key else text

    @staticmethod
    def _parse_chat(payload: Any) -> ChatResult:
        choices = payload.get('choices') if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise AIProviderError(AIErrorCode.INVALID_RESPONSE, detail='chat: no choices')
        choice = choices[0]
        finish_reason = choice.get('finish_reason') or choice.get('native_finish_reason')
        if finish_reason == 'error':
            raise AIProviderError(AIErrorCode.SERVER, detail='chat: finish_reason=error')
        if finish_reason == 'content_filter':
            raise AIProviderError(AIErrorCode.CONTENT_FILTER, detail='chat: finish_reason=content_filter')
        message = choice.get('message') if isinstance(choice.get('message'), dict) else {}
        content = message.get('content')
        if isinstance(content, list):
            # Some providers return content parts instead of a string.
            content = ''.join(part.get('text', '') for part in content if isinstance(part, dict))
        return ChatResult(
            text=content if isinstance(content, str) else '',
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            model=payload.get('model'),
            usage=payload.get('usage') or {},
        )
