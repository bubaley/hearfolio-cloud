from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.domains.library.models import Recording, ShareLink, UploadState
from app.domains.library.services.pipeline import RecordingPipeline


@pytest.fixture
def results_provider():
    calls = []

    async def provider(recording, result_ids):
        calls.append((recording.id, result_ids))
        return [{'id': str(result_id), 'title': 'Кратко', 'content': '- пункт'} for result_id in result_ids]

    RecordingPipeline.register_share_results_provider(provider)
    yield calls
    RecordingPipeline.register_share_results_provider(None)


@pytest.mark.asyncio
async def test_share_link_exposes_exactly_what_is_included(api_client, s3, library, results_provider):
    recording = await library.recording(title='Созвон', transcript='секретная расшифровка')
    url = f'/api/v1/recordings/{recording.id}/share'
    assert (await api_client.get(url, headers=library.h(library.member))).json() is None

    result_id = str(uuid4())
    response = await api_client.put(
        url,
        json={'include_audio': False, 'include_transcript': True, 'result_ids': [result_id]},
        headers=library.h(library.member),
    )
    assert response.status_code == 200
    token = response.json()['token']
    assert len(token) >= 32

    api_client.cookies.clear()
    public = await api_client.get(f'/api/v1/public/share/{token}')
    assert public.status_code == 200, public.text
    body = public.json()
    assert body['title'] == 'Созвон'
    assert body['audio'] is None
    assert body['transcript_text'] == 'секретная расшифровка'
    assert body['results'] == [{'id': result_id, 'title': 'Кратко', 'content': '- пункт'}]
    assert 'audio_key' not in body and 'created_by' not in body

    # Editing keeps the token; audio becomes a short-lived presigned URL, the transcript disappears.
    response = await api_client.put(
        url, json={'include_audio': True, 'include_transcript': False}, headers=library.h(library.member)
    )
    assert response.json()['token'] == token
    body = (await api_client.get(f'/api/v1/public/share/{token}')).json()
    assert body['transcript_text'] is None and body['transcript_segments'] is None and body['results'] == []
    assert parse_qs(urlsplit(body['audio']['url']).query)['X-Amz-Expires'] == ['600']
    assert (await ShareLink.get(token=token)).views == 2

    # Revoking makes the page 404 and the next share issues a new token.
    assert (await api_client.delete(url, headers=library.h(library.member))).status_code == 204
    assert (await api_client.get(f'/api/v1/public/share/{token}')).status_code == 404
    response = await api_client.put(url, json={}, headers=library.h(library.member))
    assert response.json()['token'] != token
    events = await api_client.get(f'/api/v1/recordings/{recording.id}/events', headers=library.h(library.member))
    assert [event['kind'] for event in events.json()].count('shared') == 2


@pytest.mark.asyncio
async def test_expired_unknown_and_deleted_links_are_404(api_client, s3, library):
    recording = await library.recording()
    assert (await api_client.get('/api/v1/public/share/nope')).status_code == 404
    link = await ShareLink.create(
        recording=recording, token='expired-token', expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    assert (await api_client.get(f'/api/v1/public/share/{link.token}')).status_code == 404
    await ShareLink.filter(id=link.id).update(expires_at=None)
    assert (await api_client.get(f'/api/v1/public/share/{link.token}')).status_code == 200
    await Recording.filter(id=recording.id).update(deleted_at=datetime.now(UTC))
    assert (await api_client.get(f'/api/v1/public/share/{link.token}')).status_code == 404


@pytest.mark.asyncio
async def test_not_uploaded_audio_is_not_exposed(api_client, s3, library):
    recording = await library.recording()
    await Recording.filter(id=recording.id).update(upload_state=UploadState.PENDING)
    link = await ShareLink.create(recording=recording, token='pending-audio')
    body = (await api_client.get(f'/api/v1/public/share/{link.token}')).json()
    assert body['audio'] is None


@pytest.mark.asyncio
async def test_share_expiry_must_be_in_the_future(api_client, library):
    recording = await library.recording()
    response = await api_client.put(
        f'/api/v1/recordings/{recording.id}/share',
        json={'expires_at': '2020-01-01T00:00:00Z'},
        headers=library.h(library.member),
    )
    assert response.status_code == 400
