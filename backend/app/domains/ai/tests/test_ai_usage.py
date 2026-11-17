from datetime import timedelta
from decimal import Decimal

import httpx2
import pytest

from app.core.utils.date_utils import utcnow
from app.domains.ai.models import AIUsage, AIUsageKind, RecordingResult
from app.domains.ai.services.openrouter_client import AIErrorCode, AIProviderError, OpenRouterClient
from app.domains.ai.services.result_service import ResultService
from app.domains.ai.services.usage_service import UsageRecorder, measured
from app.domains.ai.tests.conftest import TEXT_MODEL, FakeSegmenter
from app.domains.ai.tests.fakes import FakeProvider, chat_reply, no_sleep
from app.domains.ai.tests.test_recording_processor import GROK, _stt, _use_stt_model
from app.domains.library.models import RecordingStatus

TRANSCRIBED = {'status': RecordingStatus.TRANSCRIBED, 'transcript_text': 'Обсудили релиз и сроки.'}


def test_measured_reads_chat_tokens_and_transcription_seconds():
    assert measured(
        {
            'prompt_tokens': 1200,
            'completion_tokens': 300,
            'completion_tokens_details': {'reasoning_tokens': 120},
            'prompt_tokens_details': {'cached_tokens': 1000},
            'cost': 0.00042,
        }
    ) == {
        'input_tokens': 1200,
        'output_tokens': 300,
        'reasoning_tokens': 120,
        'cached_tokens': 1000,
        'audio_ms': None,
        'cost_usd': Decimal('0.00042'),
    }
    assert measured({'seconds': 19.188, 'cost': 0.000533})['audio_ms'] == 19188
    # Nonsense is dropped, never guessed.
    bad = measured({'prompt_tokens': -1, 'completion_tokens': True, 'seconds': 'x', 'cost': float('nan')})
    assert set(bad.values()) == {None}


@pytest.mark.asyncio
async def test_client_reports_usage_even_for_a_failed_answer(ai_team):
    seen: list[tuple[str, dict]] = []

    async def hook(model: str, usage: dict) -> None:
        seen.append((model, usage))

    provider = FakeProvider().add(
        '/chat/completions',
        chat_reply('ok', usage={'cost': 0.001}),
        # An upstream error inside a 200 is still billed.
        httpx2.Response(200, json={'model': 'm', 'error': {'code': 400, 'message': 'bad'}, 'usage': {'cost': 0.0005}}),
    )
    client = OpenRouterClient('https://router.test/api/v1', 'key', transport=provider.transport, sleep=no_sleep)
    client.on_usage = hook
    await client.chat(model='test/text', messages=[{'role': 'user', 'content': 'x'}])
    with pytest.raises(AIProviderError) as raised:
        await client.chat(model='test/text', messages=[{'role': 'user', 'content': 'x'}])
    assert raised.value.code == AIErrorCode.BAD_REQUEST
    assert [usage['cost'] for _, usage in seen] == [0.001, 0.0005]

    # A failing hook never breaks the request.
    async def broken(model: str, usage: dict) -> None:
        raise RuntimeError('db down')

    await client.aclose()
    provider = FakeProvider().add('/chat/completions', chat_reply('fine', usage={'cost': 0.1}))
    client = OpenRouterClient(
        'https://router.test/api/v1', 'key', transport=provider.transport, sleep=no_sleep, on_usage=broken
    )
    assert (await client.chat(model='test/text', messages=[{'role': 'user', 'content': 'x'}])).text == 'fine'
    await client.aclose()


@pytest.mark.asyncio
async def test_pipeline_accounts_every_request_to_whom_it_belongs(ai_team, fake_ai):
    await _use_stt_model(ai_team, fake_ai, GROK)
    recording = await ai_team.recording()
    stt = _stt(('Привет.', 1.0, 1.5), ('Да.', 3.0, 4.0), speakers=[0, 1])
    stt['usage'] = {'seconds': 1800.0, 'cost': 0.05}
    fake_ai.stt_replies = [stt]
    fake_ai.speakers = {'Спикер 1': 'Аня'}

    await ai_team.processor(FakeSegmenter(duration_ms=1_800_000)).process(recording.id)
    result = await RecordingResult.get(recording_id=recording.id)
    await ResultService.generate(result.id)

    rows = await AIUsage.filter(recording_id=recording.id).order_by('created_at')
    assert [row.kind for row in rows] == [
        AIUsageKind.TRANSCRIPTION,
        AIUsageKind.TITLE,
        AIUsageKind.TAGS,
        AIUsageKind.SPEAKERS,
        AIUsageKind.SUMMARY,
    ]
    assert all(row.user_id == ai_team.author.id and row.organization_id == ai_team.org.id for row in rows)
    assert (rows[0].audio_ms, rows[0].cost_usd, rows[0].model) == (1_800_000, Decimal('0.05'), GROK)
    assert (rows[-1].result_id, rows[-1].input_tokens, rows[-1].reasoning_tokens) == (result.id, 1000, 50)


@pytest.mark.asyncio
async def test_usage_is_for_org_admins_only(api_client, auth_headers, ai_team, fake_ai):
    recording = await ai_team.recording(**TRANSCRIBED)
    manual = await RecordingResult.create(
        recording=recording, title='Свой запрос', prompt='x', model=TEXT_MODEL, created_by=ai_team.member
    )
    await ResultService.generate(manual.id)
    record = UsageRecorder(ai_team.org.id, AIUsageKind.TRANSCRIPTION, recording.id, None, ai_team.author.id)
    await record('x-ai/grok-stt-2.0', {'seconds': 600, 'cost': 0.01})
    await record('x-ai/grok-stt-2.0', {'seconds': 60})

    url = f'/api/v1/recordings/{recording.id}/ai-usage'
    member = await auth_headers(ai_team.member, ai_team.org)
    assert (await api_client.get(url, headers=member)).status_code == 403
    admin = await auth_headers(ai_team.admin, ai_team.org)
    body = (await api_client.get(url, headers=admin)).json()
    assert [(line['kind'], line['title']) for line in body['lines']] == [
        ('transcription', None),
        ('summary', 'Свой запрос'),
    ]
    assert body['lines'][0]['audio_ms'] == 660_000
    assert body['lines'][0]['unknown_cost_requests'] == 1
    assert body['total']['cost_usd'] == pytest.approx(0.012)

    now = utcnow()
    params = {'since': (now - timedelta(days=1)).isoformat(), 'until': (now + timedelta(minutes=1)).isoformat()}
    assert (await api_client.get('/api/v1/ai-settings/usage', headers=member, params=params)).status_code == 403
    report = (await api_client.get('/api/v1/ai-settings/usage', headers=admin, params=params)).json()
    by_user = {line['user_id']: line for line in report['users']}
    # Automatic processing is the author's spending, a manual summary its requester's.
    assert by_user[str(ai_team.author.id)]['transcription_cost_usd'] == pytest.approx(0.01)
    assert by_user[str(ai_team.member.id)]['summary_cost_usd'] == pytest.approx(0.002)
    assert report['total']['cost_usd'] == pytest.approx(0.012)
    assert report['accounting_since'] is not None
    bad = {'since': params['until'], 'until': params['since']}
    assert (await api_client.get('/api/v1/ai-settings/usage', headers=admin, params=bad)).status_code == 400
