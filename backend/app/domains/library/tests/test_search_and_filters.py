from datetime import UTC, datetime

import pytest

from app.domains.library.models import Recording, RecordingStatus, RecordingVisibility, Tag


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
