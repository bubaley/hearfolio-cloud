from datetime import timedelta

import pytest

from app.core.utils.date_utils import utcnow
from app.domains.library.models import Recording, RecordingVisibility
from app.domains.library.services import recording_query


@pytest.fixture(autouse=True)
def no_overlap(request, monkeypatch):
    """Exact cursors keep these tests about paging; test_sync_overlap_* checks the safety margin."""
    if 'overlap' not in request.node.name:
        monkeypatch.setattr(recording_query, 'SYNC_OVERLAP', timedelta(0))


async def _sync_all(api_client, headers, cursor=None, limit=2):
    """Follow next_cursor until has_more is false; returns (item ids, deleted ids, final cursor, pages)."""
    items, deleted, pages = [], [], 0
    while True:
        params = {'limit': limit, **({'cursor': cursor} if cursor else {})}
        response = await api_client.get('/api/v1/recordings/sync', params=params, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        pages += 1
        items += [item['id'] for item in body['items']]
        deleted += body['deleted_ids']
        cursor = body['next_cursor']
        if not body['has_more']:
            return items, deleted, cursor, pages


@pytest.mark.asyncio
async def test_sync_pages_and_tombstones(api_client, s3, library):
    headers = library.h(library.member)
    recordings = [await library.recording(title=f'R{i}') for i in range(5)]
    personal = await library.recording(visibility=RecordingVisibility.PERSONAL)

    items, deleted, cursor, pages = await _sync_all(api_client, headers)
    assert items == [str(recording.id) for recording in recordings]
    assert pages == 3
    # Changes the member cannot see appear only as ids to drop.
    assert deleted == [str(personal.id)]
    assert cursor

    # Nothing changed: an empty page with the same cursor.
    items, deleted, same_cursor, _ = await _sync_all(api_client, headers, cursor)
    assert (items, deleted, same_cursor) == ([], [], cursor)

    # A rename, a deletion by the author and a move into a hidden project.
    hidden = await library.project(private=True, members=(library.author,))
    author = library.h(library.author)
    assert (
        await api_client.patch(f'/api/v1/recordings/{recordings[0].id}', json={'title': 'New'}, headers=author)
    ).status_code == 200
    assert (await api_client.delete(f'/api/v1/recordings/{recordings[1].id}', headers=author)).status_code == 204
    response = await api_client.patch(
        f'/api/v1/recordings/{recordings[2].id}', json={'project_id': str(hidden.id)}, headers=author
    )
    assert response.status_code == 200
    items, deleted, cursor, _ = await _sync_all(api_client, headers, cursor)
    assert items == [str(recordings[0].id)]
    assert set(deleted) == {str(recordings[1].id), str(recordings[2].id)}

    # Restoring brings it back as an item.
    assert (await api_client.post(f'/api/v1/recordings/{recordings[1].id}/restore', headers=author)).status_code == 200
    items, deleted, cursor, _ = await _sync_all(api_client, headers, cursor)
    assert (items, deleted) == ([str(recordings[1].id)], [])


@pytest.mark.asyncio
async def test_sync_items_carry_the_transcript(api_client, library):
    await library.recording(transcript='hello world')
    response = await api_client.get('/api/v1/recordings/sync', headers=library.h(library.member))
    assert response.json()['items'][0]['transcript_text'] == 'hello world'


@pytest.mark.asyncio
async def test_project_access_change_resyncs_its_recordings(api_client, library):
    project = await library.project()
    recording = await library.recording(project=project)
    _, _, cursor, _ = await _sync_all(api_client, library.h(library.member))
    response = await api_client.patch(
        f'/api/v1/projects/{project.id}', json={'is_private': True}, headers=library.h(library.author)
    )
    assert response.status_code == 200, response.text
    _, deleted, _, _ = await _sync_all(api_client, library.h(library.member), cursor)
    assert deleted == [str(recording.id)]


@pytest.mark.asyncio
async def test_invalid_cursor(api_client, library):
    response = await api_client.get(
        '/api/v1/recordings/sync', params={'cursor': 'not-a-cursor'}, headers=library.h(library.member)
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_sync_overlap_returns_rows_committed_late_behind_the_cursor(api_client, library):
    headers = library.h(library.member)
    old = await library.recording(title='Old')
    await Recording.filter(id=old.id).update(updated_at=utcnow() - timedelta(minutes=5))
    _, _, cursor, _ = await _sync_all(api_client, headers)
    # Nothing recent: the cursor is exact and the next sync is empty.
    items, _, same, _ = await _sync_all(api_client, headers, cursor)
    assert (items, same) == ([], cursor)

    fresh = await library.recording(title='Fresh')
    items, _, cursor, _ = await _sync_all(api_client, headers, cursor)
    assert items == [str(fresh.id)]

    # A transaction that set updated_at earlier but committed after that sync still shows up.
    late = await library.recording(title='Late')
    fresh_updated_at = (await Recording.get(id=fresh.id)).updated_at
    await Recording.filter(id=late.id).update(updated_at=fresh_updated_at - timedelta(seconds=1))
    items, _, _, _ = await _sync_all(api_client, headers, cursor)
    assert str(late.id) in items
    # Recent rows may come again; clients upsert them by id.
    assert set(items) <= {str(fresh.id), str(late.id)}


@pytest.mark.asyncio
async def test_sync_overlap_never_loops_when_paging(api_client, library):
    headers = library.h(library.member)
    created = [await library.recording(title=f'R{i}') for i in range(5)]
    items, _, _, pages = await _sync_all(api_client, headers, limit=2)
    assert sorted(items) == sorted(str(recording.id) for recording in created)
    assert pages == 3
