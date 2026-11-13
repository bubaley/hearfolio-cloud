from datetime import UTC, datetime, timedelta

import pytest

from app.domains.library.models import Recording, RecordingStatus, RecordingVisibility, Tag, UploadState


@pytest.mark.asyncio
async def test_search_counts_matches_and_points_at_the_first_matching_segment(api_client, library):
    segments = [
        {'start_ms': 0, 'end_ms': 4000, 'text': 'Which topic comes first today'},
        {'start_ms': 4000, 'end_ms': 9000, 'text': 'Let us review the roadmap now'},
        {'start_ms': 9000, 'end_ms': 12000, 'text': 'And the roadmap again'},
    ]
    hit = await library.recording(title='Planning', transcript='\n'.join(str(s['text']) for s in segments))
    await Recording.filter(id=hit.id).update(transcript_segments=segments)
    await library.recording(title='Roadmap in the title only')
    await library.recording(title='Plain transcript', transcript='the roadmap without segments')
    await library.recording(title='Nothing', transcript='lunch')
    headers = library.h(library.member)

    response = await api_client.get('/api/v1/recordings', params={'search': 'roadmap', 'page_size': 1}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['meta']['total'] == 3
    assert body['meta']['has_next'] is True
    response = await api_client.get(
        '/api/v1/recordings', params={'search': 'roadmap', 'page_size': 10}, headers=headers
    )
    starts = {item['title']: item['snippet_start_ms'] for item in response.json()['data']}
    assert starts == {'Planning': 4000, 'Roadmap in the title only': None, 'Plain transcript': None}

    # Without a search there is no total.
    response = await api_client.get('/api/v1/recordings', headers=headers)
    assert response.json()['meta']['total'] is None
    assert all(item['snippet_start_ms'] is None for item in response.json()['data'])


@pytest.mark.asyncio
async def test_stalled_uploads_are_flagged_and_hidden_from_others(api_client, library):
    stalled = await library.recording(title='Stalled')
    fresh = await library.recording(title='Fresh upload')
    failed = await library.recording(title='Failed upload')
    long_ago = datetime.now(UTC) - timedelta(hours=13)
    await Recording.filter(id=stalled.id).update(upload_state=UploadState.UPLOADING, updated_at=long_ago)
    await Recording.filter(id=fresh.id).update(upload_state=UploadState.PENDING)
    await Recording.filter(id=failed.id).update(upload_state=UploadState.FAILED, updated_at=long_ago)
    await library.recording(title='Done')

    async def listing(user, **params):
        response = await api_client.get('/api/v1/recordings', params=params, headers=library.h(user))
        assert response.status_code == 200, response.text
        return {item['title']: item['stalled'] for item in response.json()['data']}

    # The author sees the stalled upload, flagged; everyone else does not, unless they ask for it.
    assert await listing(library.author) == {
        'Stalled': True,
        'Fresh upload': False,
        'Failed upload': False,
        'Done': False,
    }
    assert 'Stalled' not in await listing(library.member)
    assert 'Stalled' not in await listing(library.admin)
    assert (await listing(library.member, include_stalled='true'))['Stalled'] is True
    # The detail stays reachable (and flagged) for everyone who sees it.
    response = await api_client.get(f'/api/v1/recordings/{stalled.id}', headers=library.h(library.member))
    assert response.json()['stalled'] is True

    # Any change revives it.
    await Recording.filter(id=stalled.id).update(updated_at=datetime.now(UTC))
    assert (await listing(library.member))['Stalled'] is False


@pytest.mark.asyncio
async def test_search_title_and_transcript_with_snippet(api_client, library):
    await library.recording(title='Quarterly review', transcript='Nothing relevant here at all')
    await library.recording(
        title='Weekly sync',
        transcript='First we talked about hiring. Then the roadmap for the mobile application was discussed at length.',
    )
    await library.recording(title='Lunch', transcript='Pizza or sushi')

    response = await api_client.get(
        '/api/v1/recordings', params={'search': 'roadmap'}, headers=library.h(library.member)
    )
    items = response.json()['data']
    assert [item['title'] for item in items] == ['Weekly sync']
    snippet = items[0]['snippet']
    assert [part['text'] for part in snippet if part['highlight']] == ['roadmap']
    assert 'roadmap' in ''.join(part['text'] for part in snippet)

    response = await api_client.get(
        '/api/v1/recordings', params={'search': 'quarterly'}, headers=library.h(library.member)
    )
    items = response.json()['data']
    assert [item['title'] for item in items] == ['Quarterly review']
    assert items[0]['snippet'] is None  # matched the title only

    # Without search there is no snippet; blank search is no filter.
    response = await api_client.get('/api/v1/recordings', params={'search': '  '}, headers=library.h(library.member))
    assert len(response.json()['data']) == 3
    assert all(item['snippet'] is None for item in response.json()['data'])


@pytest.mark.asyncio
async def test_search_handles_cyrillic_and_punctuation(api_client, library):
    await library.recording(title='Планёрка', transcript='Обсудили бюджет на следующий квартал')
    response = await api_client.get(
        '/api/v1/recordings', params={'search': 'бюджет'}, headers=library.h(library.member)
    )
    assert [item['title'] for item in response.json()['data']] == ['Планёрка']
    response = await api_client.get(
        '/api/v1/recordings', params={'search': "it's & | ! (broken"}, headers=library.h(library.member)
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_filters(api_client, library):
    project = await library.project()
    tag = await Tag.create(organization=library.org, name='Sales', name_key='sales')
    in_project = await library.recording(title='In project', project=project)
    tagged = await library.recording(title='Tagged')
    await tagged.tags.add(tag)
    by_member = await library.recording(title='By member', author=library.member)
    personal = await library.recording(title='Personal', author=library.member, visibility=RecordingVisibility.PERSONAL)
    old = await library.recording(title='Old')
    await Recording.filter(id=old.id).update(
        recorded_at=datetime(2026, 1, 15, 12, tzinfo=UTC), status=RecordingStatus.TRANSCRIBED
    )
    headers = library.h(library.member)

    async def titles(**params):
        response = await api_client.get('/api/v1/recordings', params=params, headers=headers)
        assert response.status_code == 200, response.text
        return {item['title'] for item in response.json()['data']}

    assert await titles(project_id=str(project.id)) == {in_project.title}
    assert await titles(tag_id=str(tag.id)) == {tagged.title}
    assert await titles(created_by_id=str(library.member.id)) == {by_member.title, personal.title}
    assert await titles(personal='true') == {personal.title}
    assert personal.title not in await titles(personal='false')
    assert await titles(status='transcribed') == {old.title}
    assert await titles(recorded_from='2026-01-15', recorded_to='2026-01-15') == {old.title}
    assert old.title not in await titles(recorded_from='2026-02-01')
