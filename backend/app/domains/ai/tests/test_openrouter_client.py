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


GROK_WORDS = {
    'text': 'Да. Нет.',
    'segments': [{'id': 0, 'start': 0, 'end': 3.0, 'text': 'Да. Нет.'}],
    'words': [
        {'word': 'Да.', 'start': 0.1, 'end': 0.4, 'speaker': 0},
        {'word': 'Нет.', 'start': 2.0, 'end': 2.3, 'speaker': 1},
    ],
}
UNSUPPORTED = 'The selected model does not support response_format "verbose_json". Use "json" instead.'


async def _transcribe(client: OpenRouterClient, model: str = 'x-ai/grok-stt'):
    return await client.transcribe(model=model, audio=b'abc', audio_format='mp3', language='ru', timeout=10)


@pytest.mark.asyncio
async def test_transcribe_asks_for_timestamps_and_speakers_and_parses_them():
    provider = FakeProvider().add('/audio/transcriptions', httpx2.Response(200, json=GROK_WORDS))
    async with make_client(provider) as client:
        result = await _transcribe(client)
    body = provider.bodies('/audio/transcriptions')[0]
    assert body['response_format'] == 'verbose_json'
    assert body['timestamp_granularities'] == ['segment', 'word']
    assert body['provider']['options']['xai'] == {'diarize': True}
    assert body['language'] == 'ru'
    assert result.text == 'Да. Нет.'
    assert [(w.text, w.start_ms, w.end_ms, w.speaker) for w in result.words] == [
        ('Да.', 100, 400, '0'),
        ('Нет.', 2000, 2300, '1'),
    ]
    assert [(s.start_ms, s.end_ms) for s in result.segments] == [(0, 3000)]


@pytest.mark.asyncio
async def test_transcribe_steps_down_on_unsupported_requests_and_remembers_the_level():
    provider = FakeProvider().add(
        '/audio/transcriptions',
        error_reply(400, 'Unknown parameter: provider.options'),
        error_reply(400, UNSUPPORTED),
        httpx2.Response(200, json={'text': 'Привет'}),
    )
    async with make_client(provider) as client:
        result = await _transcribe(client, 'x-ai/grok-stt')
        assert (result.text, result.words, result.segments) == ('Привет', [], [])
        await _transcribe(client, 'x-ai/grok-stt')
    bodies = provider.bodies('/audio/transcriptions')
    assert ['provider' in b for b in bodies[:3]] == [True, False, False]
    assert ['response_format' in b for b in bodies[:3]] == [True, True, False]
    # The plain request is exactly the old one.
    assert set(bodies[2]) == {'model', 'input_audio', 'language'}
    # The second chunk goes straight to the accepted request, in a new client too.
    assert len(bodies) == 4 and 'response_format' not in bodies[3]
    async with make_client(provider) as client:
        await _transcribe(client, 'x-ai/grok-stt')
    assert len(provider.bodies('/audio/transcriptions')) == 5
    # Other models are not affected.
    async with make_client(provider) as client:
        await _transcribe(client, 'deepgram/nova-3')
    assert provider.bodies('/audio/transcriptions')[-1]['provider'] == {'options': {'deepgram': {'diarize': True}}}


@pytest.mark.asyncio
async def test_models_without_known_diarization_skip_the_provider_options():
    provider = FakeProvider().add(
        '/audio/transcriptions', error_reply(400, UNSUPPORTED), httpx2.Response(200, json={'text': 'Привет'})
    )
    async with make_client(provider) as client:
        await _transcribe(client, 'openai/gpt-4o-mini-transcribe')
    bodies = provider.bodies('/audio/transcriptions')
    assert [('provider' in b, 'response_format' in b) for b in bodies] == [(False, True), (False, False)]


@pytest.mark.asyncio
async def test_not_found_naming_a_parameter_is_a_shape_rejection():
    provider = FakeProvider().add(
        '/audio/transcriptions',
        error_reply(404, 'No endpoints found that support the requested parameter: timestamp_granularities'),
        httpx2.Response(200, json={'text': 'Привет'}),
    )
    async with make_client(provider) as client:
        await _transcribe(client, 'openai/whisper-1')
    assert len(provider.calls('/audio/transcriptions')) == 2


@pytest.mark.asyncio
async def test_transcribe_keeps_timestamps_when_only_provider_options_are_rejected():
    provider = FakeProvider().add(
        '/audio/transcriptions', error_reply(400, 'Unknown parameter: provider'), httpx2.Response(200, json=GROK_WORDS)
    )
    async with make_client(provider) as client:
        result = await _transcribe(client)
        await _transcribe(client)
    bodies = provider.bodies('/audio/transcriptions')
    assert len(result.words) == 2
    assert [('provider' in b, b.get('response_format')) for b in bodies] == [
        (True, 'verbose_json'),
        (False, 'verbose_json'),
        (False, 'verbose_json'),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('reply', 'code'),
    [
        (error_reply(400, 'The selected model does not support large audio inputs'), AIErrorCode.TOO_LARGE),
        (error_reply(401, 'User not found'), AIErrorCode.AUTH),
        (error_reply(402, 'no credits'), AIErrorCode.PAYMENT),
        (error_reply(404, 'No endpoints found'), AIErrorCode.MODEL_UNAVAILABLE),
    ],
)
async def test_transcribe_does_not_step_down_on_other_errors(reply, code):
    provider = FakeProvider().add('/audio/transcriptions', reply)
    async with make_client(provider) as client:
        with pytest.raises(AIProviderError) as raised:
            await _transcribe(client)
    assert raised.value.code == code
    assert len(provider.calls('/audio/transcriptions')) == 1
    assert OpenRouterClient.transcription_levels == {}


@pytest.mark.asyncio
async def test_transcribe_retries_transient_errors_with_the_same_request():
    provider = FakeProvider().add('/audio/transcriptions', error_reply(503), httpx2.Response(200, json=GROK_WORDS))
    async with make_client(provider) as client:
        await _transcribe(client)
    bodies = provider.bodies('/audio/transcriptions')
    assert len(bodies) == 2 and all('provider' in b for b in bodies)
    assert OpenRouterClient.transcription_levels == {}


@pytest.mark.asyncio
async def test_transcribe_bad_request_at_every_level_raises_without_remembering():
    provider = FakeProvider().add('/audio/transcriptions', error_reply(400, 'Invalid audio file'))
    async with make_client(provider) as client:
        with pytest.raises(AIProviderError) as raised:
            await _transcribe(client)
    assert raised.value.code == AIErrorCode.BAD_REQUEST
    # One request per level, never a loop.
    assert len(provider.calls('/audio/transcriptions')) == 3
    assert OpenRouterClient.transcription_levels == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{'words': []}, ['text'], {'text': None}])
async def test_transcribe_without_text_is_an_invalid_response(payload):
    provider = FakeProvider().add('/audio/transcriptions', httpx2.Response(200, json=payload))
    async with make_client(provider, max_attempts=1) as client:
        with pytest.raises(AIProviderError) as raised:
            await _transcribe(client)
    assert raised.value.code == AIErrorCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_transcribe_ignores_malformed_timing():
    payload = {'text': 'Текст', 'words': 'nope', 'segments': [{'start': 'x'}], 'usage': 'free'}
    provider = FakeProvider().add('/audio/transcriptions', httpx2.Response(200, json=payload))
    async with make_client(provider) as client:
        result = await _transcribe(client)
    assert (result.text, result.words, result.segments, result.usage) == ('Текст', [], [], {})
