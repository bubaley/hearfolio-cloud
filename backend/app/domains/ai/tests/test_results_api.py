import importlib
import sys
from unittest.mock import AsyncMock

import pytest

from app.core.broker import broker
from app.domains.ai.models import RecordingProcessing, RecordingResult, ResultStatus, SummaryTemplate
from app.domains.ai.services import task_kicker
from app.domains.ai.services.result_service import ResultService
from app.domains.ai.tests.conftest import TEXT_MODEL
from app.domains.library.models import (
    Project,
    ProjectMember,
    RecordingEvent,
    RecordingEventKind,
    RecordingStatus,
    ShareLink,
)
from app.domains.library.services.pipeline import RecordingPipeline
from app.domains.organization.services.organization_websocket_service import OrganizationWebSocketService

TRANSCRIBED = {'status': RecordingStatus.TRANSCRIBED, 'transcript_text': 'Обсудили релиз и сроки.'}


@pytest.fixture
def kicks(monkeypatch) -> AsyncMock:
    kick = AsyncMock(return_value=True)
    monkeypatch.setattr(task_kicker.AITaskKicker, 'kick', kick)
    return kick


@pytest.fixture
def notifications(monkeypatch) -> AsyncMock:
    notify = AsyncMock()
    monkeypatch.setattr(OrganizationWebSocketService, 'notify', notify)
    return notify


@pytest.mark.asyncio
async def test_several_summaries_in_one_request_each_with_its_own_task(
    api_client, auth_headers, ai_team, kicks, notifications
):
    recording = await ai_team.recording(**TRANSCRIBED)
    templates = await SummaryTemplate.filter(organization_id=ai_team.org.id).order_by('position')
    response = await api_client.post(
        f'/api/v1/recordings/{recording.id}/results',
        headers=await auth_headers(ai_team.member, ai_team.org),
        json={'template_ids': [str(templates[2].id), str(templates[1].id)], 'custom_prompt': '  Выпиши риски  '},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert [(r['title'], r['status'], r['model']) for r in body] == [
        ('Задачи и ответственные', 'queued', TEXT_MODEL),
        ('Решения и договорённости', 'queued', TEXT_MODEL),
        ('Свой запрос', 'queued', TEXT_MODEL),
    ]
    assert body[2]['prompt'] == 'Выпиши риски'
    assert body[0]['created_by_id'] == str(ai_team.member.id)
    assert [call.args for call in kicks.await_args_list] == [('ai.generate_result', r['id']) for r in body]
    events = await RecordingEvent.filter(recording_id=recording.id, kind=RecordingEventKind.RESULT_CREATED)
    assert len(events) == 3
    sent = [call.args[1] for call in notifications.await_args_list]
    assert sent.count('result.updated') == 3 and 'recording.updated' in sent

    listed = await api_client.get(
        f'/api/v1/recordings/{recording.id}/results', headers=await auth_headers(ai_team.author, ai_team.org)
    )
    assert [r['id'] for r in listed.json()] == [r['id'] for r in body]


@pytest.mark.asyncio
async def test_summary_request_validation(api_client, auth_headers, ai_team, kicks, organization_factory):
    headers = await auth_headers(ai_team.member, ai_team.org)
    pending = await ai_team.recording()
    template = await SummaryTemplate.filter(organization_id=ai_team.org.id).first()
    assert template is not None
    url = f'/api/v1/recordings/{pending.id}/results'
    response = await api_client.post(url, headers=headers, json={'template_ids': [str(template.id)]})
    assert response.status_code == 400
    assert response.json()['error']['message'] == 'Саммари можно сделать после расшифровки'

    recording = await ai_team.recording(**TRANSCRIBED)
    url = f'/api/v1/recordings/{recording.id}/results'
    assert (await api_client.post(url, headers=headers, json={})).status_code == 400
    response = await api_client.post(url, headers=headers, json={'custom_prompt': 'x', 'model': 'not/allowed'})
    assert response.json()['error']['message'] == 'Эта модель не разрешена в организации'
    other_template = await SummaryTemplate.create(
        organization_id=(await organization_factory()).id, name='x', prompt='y'
    )
    response = await api_client.post(url, headers=headers, json={'template_ids': [str(other_template.id)]})
    assert response.json()['error']['message'] == 'Шаблон не найден'
    assert kicks.await_count == 0


@pytest.mark.asyncio
async def test_results_follow_recording_visibility(api_client, auth_headers, ai_team, kicks):
    private = await Project.create(organization=ai_team.org, name='Секрет', is_private=True)
    await ProjectMember.create(project=private, user=ai_team.author)
    recording = await ai_team.recording(project=private, **TRANSCRIBED)
    result = await RecordingResult.create(recording=recording, title='Кратко', prompt='p', model=TEXT_MODEL)
    member = await auth_headers(ai_team.member, ai_team.org)
    assert (await api_client.get(f'/api/v1/recordings/{recording.id}/results', headers=member)).status_code == 404
    assert (await api_client.get(f'/api/v1/recording-results/{result.id}', headers=member)).status_code == 404
    listed = await api_client.get('/api/v1/recording-results', headers=member)
    assert listed.json()['data'] == []
    author = await auth_headers(ai_team.author, ai_team.org)
    listed = await api_client.get(
        '/api/v1/recording-results', headers=author, params={'recording_id': str(recording.id)}
    )
    assert [r['id'] for r in listed.json()['data']] == [str(result.id)]


@pytest.mark.asyncio
async def test_delete_and_regenerate_permissions(api_client, auth_headers, ai_team, kicks):
    recording = await ai_team.recording(**TRANSCRIBED)
    own = await RecordingResult.create(
        recording=recording, title='Свой запрос', prompt='p', model=TEXT_MODEL, created_by=ai_team.member
    )
    auto = await RecordingResult.create(recording=recording, title='Кратко', prompt='p', model=TEXT_MODEL)
    member = await auth_headers(ai_team.member, ai_team.org)
    author = await auth_headers(ai_team.author, ai_team.org)
    admin = await auth_headers(ai_team.admin, ai_team.org)

    assert (await api_client.delete(f'/api/v1/recording-results/{auto.id}', headers=member)).status_code == 403
    assert (await api_client.delete(f'/api/v1/recording-results/{own.id}', headers=author)).status_code == 403
    assert (await api_client.delete(f'/api/v1/recording-results/{auto.id}', headers=author)).status_code == 204

    response = await api_client.post(f'/api/v1/recording-results/{own.id}/regenerate', headers=author)
    assert response.status_code == 201
    regenerated = response.json()
    assert (regenerated['title'], regenerated['prompt'], regenerated['status']) == ('Свой запрос', 'p', 'queued')
    assert regenerated['created_by_id'] == str(ai_team.author.id)
    assert kicks.await_args.args == ('ai.generate_result', regenerated['id'])
    assert (await api_client.delete(f'/api/v1/recording-results/{own.id}', headers=admin)).status_code == 204
    assert await RecordingResult.filter(recording_id=recording.id).count() == 1


@pytest.mark.asyncio
async def test_generate_takes_a_result_once_and_reports_failures(ai_team, fake_ai):
    recording = await ai_team.recording(**TRANSCRIBED)
    result = await RecordingResult.create(recording=recording, title='Кратко', prompt='Кратко', model=TEXT_MODEL)
    fake_ai.summary = ''
    failed = await ResultService.generate(result.id)
    assert failed is not None
    assert (failed.status, failed.error_message) == (ResultStatus.FAILED, 'Модель вернула пустой ответ')
    assert await ResultService.generate(result.id) is None
    content = fake_ai.text_requests[0]['messages'][1]['content']
    assert 'Обсудили релиз и сроки.' in content


@pytest.mark.asyncio
async def test_retry_and_retranscribe_endpoints(api_client, auth_headers, ai_team, kicks):
    headers = await auth_headers(ai_team.member, ai_team.org)
    failed = await ai_team.recording(status=RecordingStatus.FAILED)
    response = await api_client.post(f'/api/v1/recordings/{failed.id}/retry', headers=headers)
    assert response.status_code == 200
    assert kicks.await_args.args == ('ai.process_recording', str(failed.id))
    assert kicks.await_args.kwargs == {'force': True}

    done = await ai_team.recording(**TRANSCRIBED)
    assert (await api_client.post(f'/api/v1/recordings/{done.id}/retry', headers=headers)).status_code == 409

    url = f'/api/v1/recordings/{done.id}/retranscribe'
    response = await api_client.post(url, headers=headers, json={'model': 'not/allowed'})
    assert response.status_code == 400
    response = await api_client.post(url, headers=headers, json={'model': 'other/audio'})
    assert response.status_code == 200
    assert response.json()['transcript_text'] == 'Обсудили релиз и сроки.'
    processing = await RecordingProcessing.get(recording_id=done.id)
    assert processing.retranscribe_model == 'other/audio'

    busy = await ai_team.recording(status=RecordingStatus.TRANSCRIBING)
    response = await api_client.post(f'/api/v1/recordings/{busy.id}/retranscribe', headers=headers, json={})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_public_share_exposes_only_finished_selected_results(api_client, ai_team):
    RecordingPipeline.register_share_results_provider(ResultService.shared_results)
    recording = await ai_team.recording(**TRANSCRIBED)
    done = await RecordingResult.create(
        recording=recording, title='Кратко', prompt='p', model=TEXT_MODEL, status=ResultStatus.DONE, content='- да'
    )
    running = await RecordingResult.create(
        recording=recording, title='Задачи', prompt='p', model=TEXT_MODEL, status=ResultStatus.RUNNING
    )
    hidden = await RecordingResult.create(
        recording=recording, title='Скрыто', prompt='p', model=TEXT_MODEL, status=ResultStatus.DONE
    )
    await ShareLink.create(
        recording=recording, token='share-token-ai', include_audio=False, result_ids=[str(done.id), str(running.id)]
    )
    response = await api_client.get('/api/v1/public/share/share-token-ai')
    assert response.status_code == 200
    results = response.json()['results']
    assert [r['id'] for r in results] == [str(done.id)]
    assert results[0]['content'] == '- да'
    assert str(hidden.id) not in response.text


def test_tasks_are_registered_under_the_seam_names():
    module_name = 'app.domains.ai.tasks'
    already = module_name in sys.modules
    importlib.import_module(module_name)
    try:
        assert broker.find_task('ai.process_recording') is not None
        assert broker.find_task('ai.generate_result') is not None
    finally:
        if not already:
            broker.local_task_registry.pop('ai.process_recording', None)
            broker.local_task_registry.pop('ai.generate_result', None)
            sys.modules.pop(module_name, None)
