import pytest

from app.domains.library.models import ProjectMember, ProjectSuggestionState, Recording


async def _views(api_client, library, user, recording_id):
    """The recording as `user` gets it from detail, list, search and sync."""
    headers = library.h(user)
    detail = (await api_client.get(f'/api/v1/recordings/{recording_id}', headers=headers)).json()
    listed = next(
        item
        for item in (await api_client.get('/api/v1/recordings', headers=headers)).json()['data']
        if item['id'] == str(recording_id)
    )
    searched = (await api_client.get('/api/v1/recordings', params={'search': 'Секрет'}, headers=headers)).json()['data']
    synced = next(
        item
        for item in (await api_client.get('/api/v1/recordings/sync', headers=headers)).json()['items']
        if item['id'] == str(recording_id)
    )
    return [detail, listed, *searched, synced]


@pytest.mark.asyncio
async def test_suggested_private_project_is_hidden_from_non_members(api_client, s3, library):
    secret = await library.project(private=True, members=(library.author,), name='Секретный проект')
    recording = await library.recording(title='Секрет обсуждения')
    await Recording.filter(id=recording.id).update(
        suggested_project_id=secret.id, project_suggestion_state=ProjectSuggestionState.PENDING
    )

    for item in await _views(api_client, library, library.member, recording.id):
        assert item['suggested_project'] is None
        assert item['suggested_project_id'] is None
        assert item['project_suggestion_state'] == 'none'
        assert 'Секретный' not in str(item)

    for item in await _views(api_client, library, library.author, recording.id):
        assert item['suggested_project']['name'] == 'Секретный проект'
        assert item['project_suggestion_state'] == 'pending'

    # The member cannot act on a suggestion they do not see either.
    response = await api_client.post(
        f'/api/v1/recordings/{recording.id}/project-suggestion/accept', headers=library.h(library.member)
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_author_who_left_private_project_does_not_see_its_name(api_client, s3, library):
    secret = await library.project(private=True, members=(library.author, library.member), name='Секретный проект')
    recording = await library.recording(title='Секрет', project=secret)
    await ProjectMember.filter(project_id=secret.id, user_id=library.author.id).delete()

    # The author still sees their own recording, but not the project it sits in.
    for item in await _views(api_client, library, library.author, recording.id):
        assert item['project'] is None
        assert item['project_id'] is None
    # A project member still sees it.
    detail = (await api_client.get(f'/api/v1/recordings/{recording.id}', headers=library.h(library.member))).json()
    assert detail['project']['name'] == 'Секретный проект'
    # Anyone else does not see the recording at all (visibility rule).
    response = await api_client.get(f'/api/v1/recordings/{recording.id}', headers=library.h(library.admin))
    assert response.status_code == 404
