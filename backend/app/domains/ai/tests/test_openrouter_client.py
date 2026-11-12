import base64

import httpx2
import pytest

from app.domains.ai.services.openrouter_client import AIErrorCode, AIProviderError, OpenRouterClient
from app.domains.ai.tests.fakes import FakeProvider, chat_reply, error_reply, no_sleep

KEY = 'sk-or-v1-secret-test-key'


def make_client(provider: FakeProvider, **kwargs) -> OpenRouterClient:
    return OpenRouterClient('https://router.test/api/v1/', KEY, transport=provider.transport, sleep=no_sleep, **kwargs)


@pytest.mark.asyncio
async def test_chat_sends_auth_and_parses_answer():
    provider = FakeProvider().add('/chat/completions', chat_reply('Привет'))
    async with make_client(provider) as client:
        result = await client.chat(model='m', messages=[{'role': 'user', 'content': 'hi'}], max_tokens=100)
    assert result.text == 'Привет'
    assert result.finish_reason == 'stop'
    request = provider.calls('/chat/completions')[0]
    assert str(request.url) == 'https://router.test/api/v1/chat/completions'
    assert request.headers['authorization'] == f'Bearer {KEY}'
    assert provider.bodies('/chat/completions')[0]['max_tokens'] == 100


@pytest.mark.asyncio
async def test_chat_audio_sends_input_audio_part():
    provider = FakeProvider().add('/chat/completions', chat_reply('текст'))
    async with make_client(provider) as client:
        await client.chat_audio(
            model='google/gemini', prompt='Transcribe', audio=b'abc', audio_format='mp3', max_tokens=5000, timeout=10
        )
    body = provider.bodies('/chat/completions')[0]
    parts = body['messages'][-1]['content']
    assert parts[0] == {'type': 'text', 'text': 'Transcribe'}
    assert parts[1]['input_audio'] == {'data': base64.b64encode(b'abc').decode(), 'format': 'mp3'}
    assert body['temperature'] == 0
    assert body['max_tokens'] == 5000


@pytest.mark.asyncio
async def test_retries_rate_limit_and_server_errors_then_succeeds():
    provider = FakeProvider().add(
        '/chat/completions', error_reply(429, headers={'Retry-After': '1'}), error_reply(503), chat_reply('ok')
    )
    async with make_client(provider) as client:
        result = await client.chat(model='m', messages=[])
    assert result.text == 'ok'
    assert len(provider.calls('/chat/completions')) == 3


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts_with_russian_message():
    provider = FakeProvider().add('/chat/completions', error_reply(502))
    async with make_client(provider, max_attempts=2) as client:
        with pytest.raises(AIProviderError) as raised:
            await client.chat(model='m', messages=[])
    assert raised.value.code == AIErrorCode.SERVER
    assert raised.value.message == 'Сервис модели временно недоступен, попробуйте позже'
    assert len(provider.calls('/chat/completions')) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('status', 'message', 'code'),
    [
        (401, 'No auth credentials found', AIErrorCode.AUTH),
        (402, 'Insufficient credits', AIErrorCode.PAYMENT),
        (404, 'No endpoints found', AIErrorCode.MODEL_UNAVAILABLE),
        (400, 'This endpoint context length is 8192 tokens', AIErrorCode.TOO_LARGE),
        (400, 'something else', AIErrorCode.BAD_REQUEST),
    ],
)
async def test_client_errors_are_not_retried(status, message, code):
    provider = FakeProvider().add('/chat/completions', error_reply(status, message))
    async with make_client(provider) as client:
        with pytest.raises(AIProviderError) as raised:
            await client.chat(model='m', messages=[])
    assert raised.value.code == code
    assert len(provider.calls('/chat/completions')) == 1


@pytest.mark.asyncio
async def test_key_is_redacted_from_error_detail():
    provider = FakeProvider().add('/chat/completions', error_reply(400, f'bad key {KEY}'))
    async with make_client(provider) as client:
        with pytest.raises(AIProviderError) as raised:
            await client.chat(model='m', messages=[])
    assert KEY not in raised.value.detail
    assert KEY not in raised.value.message
    assert '[redacted]' in raised.value.detail


@pytest.mark.asyncio
async def test_provider_error_inside_200_is_an_error():
    provider = FakeProvider().add(
        '/chat/completions', httpx2.Response(200, json={'error': {'code': 502, 'message': 'upstream died'}})
    )
    async with make_client(provider, max_attempts=1) as client:
        with pytest.raises(AIProviderError) as raised:
            await client.chat(model='m', messages=[])
    assert raised.value.code == AIErrorCode.SERVER


@pytest.mark.asyncio
async def test_network_errors_are_retried():
    calls = {'count': 0}

    def flaky(request: httpx2.Request) -> httpx2.Response:
        calls['count'] += 1
        if calls['count'] == 1:
            raise httpx2.ConnectError('boom', request=request)
        return chat_reply('ok')

    provider = FakeProvider().add('/chat/completions', flaky)
    async with make_client(provider) as client:
        assert (await client.chat(model='m', messages=[])).text == 'ok'
    assert calls['count'] == 2


@pytest.mark.asyncio
async def test_content_parts_and_length_finish_reason_are_reported():
    provider = FakeProvider().add(
        '/chat/completions',
        httpx2.Response(
            200,
            json={
                'choices': [{'message': {'content': [{'type': 'text', 'text': 'часть'}]}, 'finish_reason': 'length'}]
            },
        ),
    )
    async with make_client(provider) as client:
        result = await client.chat(model='m', messages=[])
    assert result.text == 'часть'
    assert result.finish_reason == 'length'


@pytest.mark.asyncio
async def test_check_key_falls_back_to_models_for_compatible_apis():
    provider = FakeProvider().add('/key', error_reply(404)).add('/models', httpx2.Response(200, json={'data': []}))
    async with make_client(provider) as client:
        await client.check_key()
    assert len(provider.calls('/models')) == 1


def test_missing_key_is_not_configured():
    with pytest.raises(AIProviderError) as raised:
        OpenRouterClient('https://router.test', '')
    assert raised.value.code == AIErrorCode.NOT_CONFIGURED
