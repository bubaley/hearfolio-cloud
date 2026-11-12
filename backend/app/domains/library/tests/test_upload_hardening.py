from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from app.core.settings import settings
from app.domains.library.models import Recording, RecordingEvent, RecordingEventKind
from app.domains.library.services.pipeline import RecordingPipeline
from app.domains.library.services.recording_service import RecordingService

MIB = 1024 * 1024


def _payload(**overrides):
    return {
        'client_id': str(uuid4()),
        'recorded_at': '2026-11-10T09:00:00Z',
        'original_filename': 'Meeting.m4a',
        'audio_mime': 'audio/mp4',
        'audio_size': 1000,
        **overrides,
    }


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({'Error': {'Code': code, 'Message': code}}, operation)


@pytest.fixture
def enqueued(monkeypatch) -> AsyncMock:
    mock = AsyncMock(return_value=True)
    monkeypatch.setattr(RecordingPipeline, 'enqueue', mock)
    return mock


async def _create(api_client, library, **overrides):
    response = await api_client.post(
        '/api/v1/recordings', json=_payload(**overrides), headers=library.h(library.author)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _complete(api_client, library, recording_id, json=None):
    return await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/complete', json=json or {}, headers=library.h(library.author)
    )


@pytest.mark.asyncio
async def test_single_put_is_signed_for_the_exact_size(api_client, s3, library):
    body = await _create(api_client, library)
    query = parse_qs(urlsplit(body['upload']['url']).query)
    assert 'content-length' in query['X-Amz-SignedHeaders'][0].split(';')


@pytest.mark.asyncio
async def test_wrong_size_object_is_deleted_and_reasons_are_machine_readable(api_client, s3, library, enqueued):
    body = await _create(api_client, library)
    recording_id = body['recording']['id']
    key = (await Recording.get(id=recording_id)).audio_key

    response = await _complete(api_client, library, recording_id)
    assert response.json()['error']['details'] == {'reason': 'upload_incomplete'}

    s3.objects[key] = 5000
    response = await _complete(api_client, library, recording_id)
    assert response.status_code == 400
    assert response.json()['error']['details'] == {'reason': 'upload_size_mismatch'}
    s3.delete_object.assert_called_once_with(Bucket='media', Key=key)
    recording = await Recording.get(id=recording_id)
    assert (recording.upload_state, recording.error_code) == ('failed', 'upload_size_mismatch')

    response = await _complete(api_client, library, recording_id)
    assert response.json()['error']['details'] == {'reason': 'upload_failed'}
    enqueued.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_routes_of_a_deleted_recording_are_404(api_client, s3, library):
    body = await _create(api_client, library)
    recording_id = body['recording']['id']
    response = await api_client.delete(f'/api/v1/recordings/{recording_id}', headers=library.h(library.author))
    assert response.status_code == 204
    for path in ('upload/complete', 'upload/parts'):
        response = await api_client.post(
            f'/api/v1/recordings/{recording_id}/{path}', json={}, headers=library.h(library.author)
        )
        assert response.status_code == 404, path
        assert response.json()['error']['code'] == 'NOT_FOUND'


@pytest.mark.asyncio
async def test_storage_errors_are_a_clean_503(api_client, s3, library):
    body = await _create(api_client, library)
    s3.head_object.side_effect = _client_error('InternalError', 'HeadObject')
    response = await _complete(api_client, library, body['recording']['id'])
    assert response.status_code == 503
    assert response.json()['error']['details'] == {'reason': 'storage_unavailable'}


@pytest.mark.asyncio
async def test_oversized_parts_are_aborted_before_assembly(api_client, s3, library, enqueued, monkeypatch):
    monkeypatch.setattr(settings, 'upload_multipart_threshold_bytes', 10 * MIB)
    monkeypatch.setattr(settings, 'upload_part_size_bytes', 8 * MIB)
    body = await _create(api_client, library, audio_size=20 * MIB)
    recording_id = body['recording']['id']
    s3.list_parts.return_value = {
        'Parts': [{'PartNumber': n, 'ETag': f'"e{n}"', 'Size': 5 * 1024 * MIB} for n in (1, 2, 3)],
        'IsTruncated': False,
    }
    response = await _complete(api_client, library, recording_id)
    assert response.json()['error']['details'] == {'reason': 'upload_size_mismatch'}
    s3.complete_multipart_upload.assert_not_called()
    s3.abort_multipart_upload.assert_called_once()
    assert (await Recording.get(id=recording_id)).upload_state == 'failed'

    # Part numbers beyond the plan are refused.
    s3.abort_multipart_upload.reset_mock()
    response = await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/parts', json={}, headers=library.h(library.author)
    )
    assert response.json()['parts_count'] == 3
    response = await _complete(api_client, library, recording_id, {'parts': [{'part_number': 9, 'etag': '"x"'}]})
    assert response.json()['error']['details']['reason'] == 'upload_parts_missing'


@pytest.mark.asyncio
async def test_dead_multipart_upload_is_replaced(api_client, s3, library, enqueued, monkeypatch):
    monkeypatch.setattr(settings, 'upload_multipart_threshold_bytes', 10 * MIB)
    monkeypatch.setattr(settings, 'upload_part_size_bytes', 8 * MIB)
    body = await _create(api_client, library, audio_size=20 * MIB)
    recording_id = body['recording']['id']
    s3.list_parts.side_effect = _client_error('NoSuchUpload', 'ListParts')
    s3.create_multipart_upload.return_value = {'UploadId': 'upload-2'}

    # upload/parts notices the expired upload and starts a new one (state is still `uploading`).
    response = await api_client.post(
        f'/api/v1/recordings/{recording_id}/upload/parts', json={}, headers=library.h(library.author)
    )
    assert response.status_code == 200, response.text
    assert response.json()['upload_id'] == 'upload-2'
    assert [part['part_number'] for part in response.json()['parts']] == [1, 2, 3]

    # complete on an expired upload: a new upload is started and the client is told to re-upload.
    s3.create_multipart_upload.return_value = {'UploadId': 'upload-3'}
    response = await _complete(api_client, library, recording_id)
    assert response.json()['error']['details'] == {'reason': 'upload_expired'}
    assert (await Recording.get(id=recording_id)).upload_id == 'upload-3'
    enqueued.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_completes_mark_uploaded_once(s3, library, enqueued):
    recording = await library.recording()
    await Recording.filter(id=recording.id).update(upload_state='uploading', status='awaiting_upload')
    first, second = await Recording.get(id=recording.id), await Recording.get(id=recording.id)
    await RecordingService.mark_uploaded(first)
    again = await RecordingService.mark_uploaded(second)
    assert again.upload_state == 'uploaded'
    enqueued.assert_awaited_once()
    assert await RecordingEvent.filter(recording_id=recording.id, kind=RecordingEventKind.UPLOADED).count() == 1


@pytest.mark.asyncio
async def test_audio_mime_must_be_audio_or_video(api_client, s3, library):
    for mime in ('text/html', 'application/octet-stream', 'audio/mp4\r\nX-Evil: 1', 'image/svg+xml'):
        response = await api_client.post(
            '/api/v1/recordings', json=_payload(audio_mime=mime), headers=library.h(library.author)
        )
        assert response.status_code == 400, mime
    for mime in ('audio/webm;codecs=opus', 'video/mp4', 'audio/mpeg'):
        response = await api_client.post(
            '/api/v1/recordings', json=_payload(audio_mime=mime), headers=library.h(library.author)
        )
        assert response.status_code == 201, mime


@pytest.mark.asyncio
async def test_audio_url_sets_the_stored_content_type(api_client, s3, library):
    recording = await library.recording()
    response = await api_client.get(f'/api/v1/recordings/{recording.id}/audio', headers=library.h(library.author))
    query = parse_qs(urlsplit(response.json()['url']).query)
    assert query['response-content-type'] == ['audio/mp4']
    assert query['response-content-disposition'] == ['inline']


@pytest.mark.asyncio
async def test_generated_title_can_be_marked_auto(api_client, s3, library):
    body = await _create(api_client, library, title='Запись 13.11 10:05', title_source='auto')
    assert body['recording']['title_source'] == 'auto'
    assert body['recording']['title'] == 'Запись 13.11 10:05'
    body = await _create(api_client, library, title='Планёрка')
    assert body['recording']['title_source'] == 'user'
