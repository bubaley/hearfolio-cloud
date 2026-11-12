import pytest

from app.domains.library.models import RecordingVisibility
from app.domains.library.services.visibility import LibraryVisibility

# who: author / member / admin; True = sees the recording
MATRIX = {
    'no_project': {'author': True, 'member': True, 'admin': True},
    'public_project': {'author': True, 'member': True, 'admin': True},
    'private_project_member_is_in': {'author': True, 'member': True, 'admin': False},
    'private_project_member_is_not_in': {'author': True, 'member': False, 'admin': False},
    'private_project_admin_is_in': {'author': True, 'member': False, 'admin': True},
    'personal': {'author': True, 'member': False, 'admin': False},
    'personal_in_public_project': {'author': True, 'member': False, 'admin': False},
    'personal_in_private_project_member_is_in': {'author': True, 'member': False, 'admin': False},
    'deleted': {'author': False, 'member': False, 'admin': False},
}


@pytest.fixture
async def matrix(library):
    public = await library.project(name='Public')
    with_member = await library.project(private=True, members=(library.author, library.member), name='With member')
    only_author = await library.project(private=True, members=(library.author,), name='Only author')
    with_admin = await library.project(private=True, members=(library.admin,), name='With admin')
    personal = RecordingVisibility.PERSONAL
    recordings = {
        'no_project': await library.recording(),
        'public_project': await library.recording(project=public),
        'private_project_member_is_in': await library.recording(project=with_member),
        'private_project_member_is_not_in': await library.recording(project=only_author),
        # The author is not a member of this private project: authors always see their own recordings.
        'private_project_admin_is_in': await library.recording(project=with_admin),
        'personal': await library.recording(visibility=personal),
        'personal_in_public_project': await library.recording(project=public, visibility=personal),
        'personal_in_private_project_member_is_in': await library.recording(project=with_member, visibility=personal),
        'deleted': await library.recording(deleted=True),
    }
    foreign = await library.recording(author=library.outsider, organization=library.other_org)
    return recordings, foreign


def _users(library):
    return {'author': library.author, 'member': library.member, 'admin': library.admin}


@pytest.mark.asyncio
async def test_queryset_helper_matrix(library, matrix):
    recordings, foreign = matrix
    for role, user in _users(library).items():
        visible = set(await LibraryVisibility.recordings(user, library.org.id).values_list('id', flat=True))
        expected = {recordings[name].id for name, row in MATRIX.items() if row[role]}
        assert visible == expected, role
        assert foreign.id not in visible
    # The outsider sees nothing of this organization, even when asking for it explicitly.
    assert not await LibraryVisibility.recordings(library.outsider, library.org.id).exists()
    assert set(
        await LibraryVisibility.recordings(library.outsider, library.other_org.id).values_list('id', flat=True)
    ) == {foreign.id}


@pytest.mark.asyncio
async def test_deleted_recordings_follow_the_same_rule(library, matrix):
    recordings, _ = matrix
    trash = await LibraryVisibility.recordings(library.member, library.org.id, deleted=True).values_list(
        'id', flat=True
    )
    assert trash == [recordings['deleted'].id]
    personal_deleted = await library.recording(visibility=RecordingVisibility.PERSONAL, deleted=True)
    assert (
        not await LibraryVisibility.recordings(library.member, library.org.id, deleted=True)
        .filter(id=personal_deleted.id)
        .exists()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['author', 'member', 'admin'])
async def test_every_endpoint_applies_the_rule(api_client, s3, library, matrix, role):
    recordings, foreign = matrix
    user = _users(library)[role]
    headers = library.h(user)

    listed = await api_client.get('/api/v1/recordings', headers=headers)
    assert listed.status_code == 200
    expected = {str(recordings[name].id) for name, row in MATRIX.items() if row[role]}
    assert {item['id'] for item in listed.json()['data']} == expected

    synced = await api_client.get('/api/v1/recordings/sync', headers=headers)
    assert {item['id'] for item in synced.json()['items']} == expected

    for name, recording in [*recordings.items(), ('foreign', foreign)]:
        sees = name != 'foreign' and MATRIX[name][role]
        for path in ('', '/audio', '/events', '/share'):
            response = await api_client.get(f'/api/v1/recordings/{recording.id}{path}', headers=headers)
            assert response.status_code == (200 if sees else 404), (name, path, response.text)
        patch = await api_client.patch(f'/api/v1/recordings/{recording.id}', json={'title': 'Renamed'}, headers=headers)
        assert patch.status_code == (200 if sees else 404), (name, patch.text)
        share = await api_client.put(f'/api/v1/recordings/{recording.id}/share', json={}, headers=headers)
        assert share.status_code == (200 if sees else 404), (name, share.text)


@pytest.mark.asyncio
async def test_outsider_cannot_reach_the_organization(api_client, library, matrix):
    recordings, _ = matrix
    headers = {**library.h(library.outsider), 'Organization-Key': library.org.key}
    response = await api_client.get('/api/v1/recordings', headers=headers)
    assert response.status_code == 400
    response = await api_client.get(
        f'/api/v1/recordings/{recordings["no_project"].id}', headers=library.h(library.outsider)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_search_respects_visibility(api_client, library):
    project = await library.project(private=True, members=(library.author,))
    await library.recording(title='Budget planning', transcript='We discussed the budget')
    await library.recording(title='Secret budget', project=project)
    await library.recording(title='Personal budget', visibility=RecordingVisibility.PERSONAL)
    response = await api_client.get(
        '/api/v1/recordings', params={'search': 'budget'}, headers=library.h(library.member)
    )
    assert [item['title'] for item in response.json()['data']] == ['Budget planning']
    response = await api_client.get(
        '/api/v1/recordings', params={'search': 'budget'}, headers=library.h(library.author)
    )
    assert len(response.json()['data']) == 3


@pytest.mark.asyncio
async def test_project_visibility(api_client, library):
    public = await library.project(name='Public')
    mine = await library.project(private=True, members=(library.member,), name='Mine')
    hidden = await library.project(private=True, members=(library.author,), name='Hidden')

    listed = await api_client.get('/api/v1/projects', headers=library.h(library.member))
    assert {item['id'] for item in listed.json()['data']} == {str(public.id), str(mine.id)}
    assert (await api_client.get(f'/api/v1/projects/{hidden.id}', headers=library.h(library.member))).status_code == 404

    # Admins see every private project in settings, but not in the pickers.
    picker = await api_client.get('/api/v1/projects', headers=library.h(library.admin))
    assert {item['id'] for item in picker.json()['data']} == {str(public.id)}
    manage = await api_client.get('/api/v1/projects/manage', headers=library.h(library.admin))
    assert {item['id'] for item in manage.json()} == {str(public.id), str(mine.id), str(hidden.id)}
    manage = await api_client.get('/api/v1/projects/manage', headers=library.h(library.member))
    assert {item['id'] for item in manage.json()} == {str(public.id), str(mine.id)}
