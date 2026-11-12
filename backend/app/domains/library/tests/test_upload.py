import re
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.core.settings import settings
from app.domains.library.models import Recording, RecordingEvent, RecordingEventKind
from app.domains.library.services.pipeline import RecordingPipeline


def _payload(**overrides):
    return {
        'client_id': str(uuid4()),
        'recorded_at': '2026-11-10T09:00:00Z',
        'duration_ms': 60_000,
        'source': 'desktop',
        'original_filename': 'Meeting.M4A',
        'audio_mime': 'audio/mp4',
        'audio_size': 1000,
        **overrides,
    }


@pytest.fixture
def enqueued(monkeypatch) -> AsyncMock:
    mock = AsyncMock(return_value=True)
    monkeypatch.setattr(RecordingPipeline, 'enqueue', mock)
    return mock


@pytest.mark.asyncio
async def test_single_upload_flow(api_client, s3, library, enqueued):
    response = await api_client.post('/api/v1/recordings', json=_payload(), headers=library.h(library.author))
    assert response.status_code == 201, response.text
    body = response.json()
    recording = body['recording']
    assert recording['status'] == 'awaiting_upload'
    assert recording['upload_state'] == 'pending'
    assert recording['title_source'] == 'auto'
    plan = body['upload']
    assert plan['method'] == 'single'
    assert plan['headers'] == {'Content-Type': 'audio/mp4'}
    key = (await Recording.get(id=recording['id'])).audio_key
    assert re.fullmatch(r'hearfolio/\d{4}/\d{2}/\d{2}/[0-9a-f]{32}\.m4a', key)
    assert urlsplit(plan['url']).path.endswith(key)

    # Not uploaded yet: the client may retry later, nothing is marked failed.
    response = await api_client.post(
        f'/api/v1/recordings/{recording["id"]}/upload/complete', json={}, headers=library.h(library.author)
    )
    assert response.status_code == 400
    enqueued.assert_not_awaited()

    s3.objects[key] = 1000
    response = await api_client.post(
        f'/api/v1/recordings/{recording["id"]}/upload/complete', json={}, headers=library.h(library.author)
    )
    assert response.status_code == 200, response.text
    assert response.json()['upload_state'] == 'uploaded'
    assert response.json()['status'] == 'queued'
    enqueued.assert_awaited_once()

    # Repeating `complete` is harmless and does not enqueue twice.
    response = await api_client.post(
        f'/api/v1/recordings/{recording["id"]}/upload/complete', json={}, headers=library.h(library.author)
    )
    assert response.status_code == 200
    enqueued.assert_awaited_once()
    kinds = await RecordingEvent.filter(recording_id=recording['id']).values_list('kind', flat=True)
    assert set(kinds) == {RecordingEventKind.CREATED, RecordingEventKind.UPLOADED}


@pytest.mark.asyncio
async def test_create_is_idempotent_on_client_id(api_client, s3, library):
    payload = _payload(title='Планёрка')
    first = await api_client.post('/api/v1/recordings', json=payload, headers=library.h(library.author))
    second = await api_client.post('/api/v1/recordings', json=payload, headers=library.h(library.author))
    assert first.status_code == second.status_code == 201
    assert first.json()['recording']['id'] == second.json()['recording']['id']
    assert second.json()['upload'] is not None
    assert first.json()['recording']['title_source'] == 'user'
    assert await Recording.filter(client_id=payload['client_id']).count() == 1

    # Another member re-using the id gets a conflict, not someone else's recording.
    other = await api_client.post('/api/v1/recordings', json=payload, headers=library.h(library.member))
    assert other.status_code == 409

    # Once uploaded, a re-send returns the recording without an upload plan.
    s3.objects[(await Recording.get(client_id=payload['client_id'])).audio_key] = 1000
    recording_id = first.json()['recording']['id']
    await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/complete', json={}, headers=library.h(library.author)
    )
    third = await api_client.post('/api/v1/recordings', json=payload, headers=library.h(library.author))
    assert third.json()['upload'] is None


@pytest.mark.asyncio
async def test_multipart_flow(api_client, s3, library, enqueued, monkeypatch):
    monkeypatch.setattr(settings, 'upload_multipart_threshold_bytes', 10 * 1024 * 1024)
    monkeypatch.setattr(settings, 'upload_part_size_bytes', 8 * 1024 * 1024)
    size = 20 * 1024 * 1024
    response = await api_client.post(
        '/api/v1/recordings', json=_payload(audio_size=size), headers=library.h(library.author)
    )
    assert response.status_code == 201, response.text
    recording_id = response.json()['recording']['id']
    plan = response.json()['upload']
    assert plan['method'] == 'multipart'
    assert plan['upload_id'] == 'upload-1'
    assert plan['part_size'] == 8 * 1024 * 1024
    assert plan['parts_count'] == 3
    assert [part['part_number'] for part in plan['parts']] == [1, 2, 3]
    query = parse_qs(urlsplit(plan['parts'][1]['url']).query)
    assert query['partNumber'] == ['2'] and query['uploadId'] == ['upload-1']
    assert response.json()['recording']['upload_state'] == 'uploading'

    # Resume: refresh only the missing part.
    response = await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/parts', json={'part_numbers': [3]}, headers=library.h(library.author)
    )
    assert [part['part_number'] for part in response.json()['parts']] == [3]
    response = await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/parts', json={'part_numbers': [4]}, headers=library.h(library.author)
    )
    assert response.status_code == 400

    # Only the author uploads.
    response = await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/parts', json={}, headers=library.h(library.member)
    )
    assert response.status_code == 403

    # Missing parts are rejected before S3 is asked to assemble the object.
    response = await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/complete',
        json={'parts': [{'part_number': 1, 'etag': '"a"'}]},
        headers=library.h(library.author),
    )
    assert response.status_code == 400
    assert response.json()['error']['details'] == {'reason': 'upload_parts_missing', 'missing_parts': [1, 2, 3]}
    s3.complete_multipart_upload.assert_not_called()

    # Without `parts` the server lists them itself.
    s3.list_parts.return_value = {
        'Parts': [
            {'PartNumber': n, 'ETag': f'"e{n}"', 'Size': part}
            for n, part in ((1, 8 * 1024 * 1024), (2, 8 * 1024 * 1024), (3, 4 * 1024 * 1024))
        ],
        'IsTruncated': False,
    }
    key = (await Recording.get(id=recording_id)).audio_key
    s3.objects[key] = size
    response = await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/complete', json={}, headers=library.h(library.author)
    )
    assert response.status_code == 200, response.text
    assert response.json()['upload_state'] == 'uploaded'
    s3.complete_multipart_upload.assert_called_once()
    sent = s3.complete_multipart_upload.call_args.kwargs['MultipartUpload']['Parts']
    assert sent == [{'PartNumber': n, 'ETag': f'"e{n}"'} for n in (1, 2, 3)]
    enqueued.assert_awaited_once()
    assert (await Recording.get(id=recording_id)).upload_id is None


@pytest.mark.asyncio
async def test_size_mismatch_fails_the_upload_and_restart_issues_a_new_plan(api_client, s3, library, enqueued):
    response = await api_client.post('/api/v1/recordings', json=_payload(), headers=library.h(library.author))
    recording_id = response.json()['recording']['id']
    s3.objects[(await Recording.get(id=recording_id)).audio_key] = 999
    response = await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/complete', json={}, headers=library.h(library.author)
    )
    assert response.status_code == 400
    recording = await Recording.get(id=recording_id)
    assert recording.upload_state == 'failed'
    assert recording.error_message
    enqueued.assert_not_awaited()

    response = await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/parts', json={}, headers=library.h(library.author)
    )
    assert response.status_code == 200
    assert response.json()['method'] == 'single'
    assert (await Recording.get(id=recording_id)).upload_state == 'pending'


@pytest.mark.asyncio
async def test_existing_transcript_skips_transcription(api_client, s3, library, enqueued):
    payload = _payload(
        transcript_text='Привет, это расшифровка',
        transcript_segments=[{'start_ms': 0, 'end_ms': 1500, 'text': 'Привет, это расшифровка'}],
        transcription_model='local/whisper',
        language='ru',
    )
    response = await api_client.post('/api/v1/recordings', json=payload, headers=library.h(library.author))
    recording = response.json()['recording']
    assert recording['status'] == 'transcribed'
    assert recording['transcript_segments'][0]['text'] == 'Привет, это расшифровка'
    s3.objects[(await Recording.get(id=recording['id'])).audio_key] = 1000
    response = await api_client.post(
        f'/api/v1/recordings/{recording["id"]}/upload/complete', json={}, headers=library.h(library.author)
    )
    # Still handed to the pipeline (title, tags, summaries), but the status stays `transcribed`.
    assert response.json()['status'] == 'transcribed'
    enqueued.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_checks_project_and_tags(api_client, s3, library):
    hidden = await library.project(private=True, members=(library.member,))
    response = await api_client.post(
        '/api/v1/recordings', json=_payload(project_id=str(hidden.id)), headers=library.h(library.author)
    )
    assert response.status_code == 400
    response = await api_client.post(
        '/api/v1/recordings', json=_payload(project_id=str(hidden.id)), headers=library.h(library.member)
    )
    assert response.status_code == 201
    assert response.json()['recording']['project']['id'] == str(hidden.id)

    response = await api_client.post(
        '/api/v1/recordings', json=_payload(tag_ids=[str(uuid4())]), headers=library.h(library.author)
    )
    assert response.status_code == 400
    response = await api_client.post(
        '/api/v1/recordings', json=_payload(audio_size=settings.upload_max_bytes + 1), headers=library.h(library.author)
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_pipeline_enqueue_without_ai_task_is_a_noop(library):
    recording = await library.recording()
    assert await RecordingPipeline.enqueue(recording) is False
