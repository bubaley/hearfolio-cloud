import pytest

from app.domains.library.models import (
    ProjectMember,
    Recording,
    RecordingEvent,
    RecordingEventKind,
    RecordingVisibility,
    Tag,
)


@pytest.mark.asyncio
async def test_delete_and_restore_author_or_admin(api_client, library):
    recording = await library.recording()
    url = f'/api/v1/recordings/{recording.id}'
    assert (await api_client.delete(url, headers=library.h(library.member))).status_code == 403
    assert (await api_client.delete(url, headers=library.h(library.admin))).status_code == 204
    assert (await Recording.get(id=recording.id)).deleted_at is not None
    assert (await api_client.get(url, headers=library.h(library.author))).status_code == 404

    trash = await api_client.get('/api/v1/recordings', params={'deleted': 'true'}, headers=library.h(library.member))
    assert [item['id'] for item in trash.json()['data']] == [str(recording.id)]
    assert (await api_client.post(f'{url}/restore', headers=library.h(library.member))).status_code == 403
    assert (await api_client.post(f'{url}/restore', headers=library.h(library.author))).status_code == 200
    assert (await Recording.get(id=recording.id)).deleted_at is None
    kinds = await RecordingEvent.filter(recording_id=recording.id).values_list('kind', flat=True)
    assert set(kinds) == {RecordingEventKind.DELETED, RecordingEventKind.RESTORED}


@pytest.mark.asyncio
async def test_visibility_change_is_author_only(api_client, library):
    recording = await library.recording()
    url = f'/api/v1/recordings/{recording.id}'
    for user in (library.member, library.admin):
        response = await api_client.patch(url, json={'visibility': 'personal'}, headers=library.h(user))
        assert response.status_code == 403
    response = await api_client.patch(url, json={'visibility': 'personal'}, headers=library.h(library.author))
    assert response.status_code == 200
    assert response.json()['visibility'] == RecordingVisibility.PERSONAL
    # Sending the unchanged value is not a change.
    response = await api_client.patch(
        url, json={'visibility': 'personal', 'title': 'Мой'}, headers=library.h(library.author)
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_member_edits_title_project_and_tags(api_client, library):
    recording = await library.recording(title='Auto title')
    project = await library.project()
    hidden = await library.project(private=True, members=(library.author,))
    tag_a = await Tag.create(organization=library.org, name='A', name_key='a')
    tag_b = await Tag.create(organization=library.org, name='B', name_key='b')
    url = f'/api/v1/recordings/{recording.id}'
    headers = library.h(library.member)

    response = await api_client.patch(
        url,
        json={'title': '  Новое   имя ', 'project_id': str(project.id), 'tag_ids': [str(tag_a.id), str(tag_b.id)]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['title'] == 'Новое имя'
    assert body['title_source'] == 'user'
    assert body['project_id'] == str(project.id)
    assert {tag['name'] for tag in body['tags']} == {'A', 'B'}
    # Sending the current project again is not a move (it used to take the recording out of it).
    response = await api_client.patch(url, json={'project_id': str(project.id)}, headers=headers)
    assert response.json()['project_id'] == str(project.id)

    # A project the member cannot see is rejected; null removes the project.
    assert (await api_client.patch(url, json={'project_id': str(hidden.id)}, headers=headers)).status_code == 400
    response = await api_client.patch(url, json={'project_id': None, 'tag_ids': [str(tag_b.id)]}, headers=headers)
    assert response.json()['project_id'] is None
    assert [tag['name'] for tag in response.json()['tags']] == ['B']

    events = await api_client.get(f'{url}/events', headers=headers)
    kinds = [event['kind'] for event in events.json()]
    assert kinds.count('moved') == 2 and kinds.count('tagged') == 2 and kinds.count('renamed') == 1
    renamed = next(event for event in events.json() if event['kind'] == 'renamed')
    assert renamed['data'] == {'from': 'Auto title', 'to': 'Новое имя'}
    assert renamed['actor']['id'] == str(library.member.id)


@pytest.mark.asyncio
async def test_tags_are_unique_case_insensitively_and_managed_by_admins(api_client, library):
    headers = library.h(library.member)
    response = await api_client.post('/api/v1/tags', json={'name': ' Sales  team '}, headers=headers)
    assert response.status_code == 201
    tag = response.json()
    assert tag['name'] == 'Sales team'
    assert tag['color']
    assert (await api_client.post('/api/v1/tags', json={'name': 'SALES TEAM'}, headers=headers)).status_code == 409

    url = f'/api/v1/tags/{tag["id"]}'
    assert (await api_client.patch(url, json={'color': 'red'}, headers=headers)).status_code == 403
    assert (await api_client.delete(url, headers=headers)).status_code == 403
    response = await api_client.patch(url, json={'color': 'red', 'name': 'Sales'}, headers=library.h(library.admin))
    assert response.status_code == 200
    assert response.json()['color'] == 'red'


@pytest.mark.asyncio
async def test_tag_merge(api_client, library):
    source = await Tag.create(organization=library.org, name='Client', name_key='client')
    target = await Tag.create(organization=library.org, name='Customer', name_key='customer')
    both = await library.recording()
    only_source = await library.recording()
    await both.tags.add(source, target)
    await only_source.tags.add(source)
    url = f'/api/v1/tags/{source.id}/merge'
    assert (
        await api_client.post(url, json={'target_id': str(target.id)}, headers=library.h(library.member))
    ).status_code == 403
    response = await api_client.post(url, json={'target_id': str(target.id)}, headers=library.h(library.admin))
    assert response.status_code == 200
    assert not await Tag.exists(id=source.id)
    for recording in (both, only_source):
        assert [tag.name for tag in await recording.tags.all()] == ['Customer']


@pytest.mark.asyncio
async def test_private_projects(api_client, library):
    response = await api_client.post(
        '/api/v1/projects', json={'name': 'Секретный', 'is_private': True}, headers=library.h(library.member)
    )
    assert response.status_code == 201
    project_id = response.json()['id']
    assert [member['user_id'] for member in response.json()['members']] == [str(library.member.id)]

    # The author cannot see it, the admin can manage it.
    assert (
        await api_client.get(f'/api/v1/projects/{project_id}', headers=library.h(library.author))
    ).status_code == 404
    url = f'/api/v1/projects/{project_id}/members'
    response = await api_client.post(url, json={'user_id': str(library.author.id)}, headers=library.h(library.admin))
    assert response.status_code == 201
    assert (
        await api_client.post(url, json={'user_id': str(library.author.id)}, headers=library.h(library.member))
    ).status_code == 409
    response = await api_client.post(url, json={'user_id': str(library.outsider.id)}, headers=library.h(library.member))
    assert response.status_code == 400
    assert (
        await api_client.get(f'/api/v1/projects/{project_id}', headers=library.h(library.author))
    ).status_code == 200

    # Only the creator or an admin makes it public again.
    response = await api_client.patch(
        f'/api/v1/projects/{project_id}', json={'is_private': False}, headers=library.h(library.author)
    )
    assert response.status_code == 403
    response = await api_client.patch(
        f'/api/v1/projects/{project_id}', json={'name': 'Переименован'}, headers=library.h(library.author)
    )
    assert response.status_code == 200

    response = await api_client.delete(f'{url}/{library.author.id}', headers=library.h(library.member))
    assert response.status_code == 204
    assert not await ProjectMember.exists(project_id=project_id, user_id=library.author.id)
    assert (
        await api_client.delete(f'/api/v1/projects/{project_id}', headers=library.h(library.author))
    ).status_code == 404
    assert (
        await api_client.delete(f'/api/v1/projects/{project_id}', headers=library.h(library.admin))
    ).status_code == 204


@pytest.mark.asyncio
async def test_public_project_editing_and_archiving(api_client, library):
    project = await library.project()
    url = f'/api/v1/projects/{project.id}'
    response = await api_client.patch(url, json={'emoji': '🎧', 'archived': True}, headers=library.h(library.member))
    assert response.status_code == 200
    assert response.json()['emoji'] == '🎧'
    assert response.json()['archived_at'] is not None
    listed = await api_client.get('/api/v1/projects', params={'archived': 'false'}, headers=library.h(library.member))
    assert listed.json()['data'] == []
    assert (await api_client.delete(url, headers=library.h(library.member))).status_code == 403
