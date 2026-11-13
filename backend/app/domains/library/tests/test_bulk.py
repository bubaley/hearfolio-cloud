import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domains.library.models import (
    ProjectSuggestionState,
    Recording,
    RecordingEvent,
    RecordingEventKind,
    RecordingVisibility,
    Tag,
)
from app.domains.organization.services.organization_websocket_service import OrganizationWebSocketService

URL = '/api/v1/recordings/bulk'


def _skipped(response) -> dict[str, str]:
    return {item['id']: item['reason'] for item in response.json()['skipped']}


@pytest.mark.asyncio
async def test_bulk_move_skips_invisible_and_journals(api_client, library):
    project = await library.project(name='Target')
    suggested = await library.recording(title='Suggested')
    await Recording.filter(id=suggested.id).update(
        suggested_project_id=project.id, project_suggestion_state=ProjectSuggestionState.PENDING
    )
    plain = await library.recording(title='Plain')
    already = await library.recording(title='Already', project=project)
    personal = await library.recording(author=library.author, visibility=RecordingVisibility.PERSONAL)
    foreign = await library.recording(organization=library.other_org, author=library.outsider)
    unknown = uuid4()

    response = await api_client.post(
        URL,
        json={
            'action': 'move',
            'project_id': str(project.id),
            'ids': [str(r) for r in (suggested.id, plain.id, already.id, personal.id, foreign.id, unknown, plain.id)],
        },
        headers=library.h(library.member),
    )
    assert response.status_code == 200, response.text
    assert response.json()['updated'] == [str(suggested.id), str(plain.id), str(already.id)]
    assert _skipped(response) == {
        str(personal.id): 'not_found',
        str(foreign.id): 'not_found',
        str(unknown): 'not_found',
    }

    assert await Recording.filter(project_id=project.id).count() == 3
    await suggested.refresh_from_db()
    assert suggested.project_suggestion_state == ProjectSuggestionState.ACCEPTED
    moved = await RecordingEvent.filter(kind=RecordingEventKind.MOVED).values_list('recording_id', flat=True)
    assert set(moved) == {suggested.id, plain.id}  # `already` did not change
    assert (await Recording.get(id=personal.id)).project_id is None

    # Null takes them out of the project; a project the caller cannot see is a 400 for the whole request.
    response = await api_client.post(
        URL, json={'action': 'move', 'project_id': None, 'ids': [str(plain.id)]}, headers=library.h(library.member)
    )
    assert response.status_code == 200
    assert (await Recording.get(id=plain.id)).project_id is None
    private = await library.project(private=True, members=(library.author,))
    response = await api_client.post(
        URL,
        json={'action': 'move', 'project_id': str(private.id), 'ids': [str(plain.id)]},
        headers=library.h(library.member),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_bulk_tags_add_and_remove(api_client, library):
    sales = await Tag.create(organization=library.org, name='Sales', name_key='sales')
    urgent = await Tag.create(organization=library.org, name='Urgent', name_key='urgent')
    foreign_tag = await Tag.create(organization=library.other_org, name='X', name_key='x')
    first = await library.recording()
    second = await library.recording()
    await second.tags.add(urgent)
    headers = library.h(library.member)

    response = await api_client.post(
        URL,
        json={
            'action': 'tags',
            'ids': [str(first.id), str(second.id)],
            'add_tag_ids': [str(sales.id)],
            'remove_tag_ids': [str(urgent.id)],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    for recording in (first, second):
        assert [tag.id for tag in await recording.tags.all()] == [sales.id]
    tagged = await RecordingEvent.filter(recording_id=second.id, kind=RecordingEventKind.TAGGED).first()
    assert tagged is not None
    assert tagged.data == {'added': ['Sales'], 'removed': ['Urgent']}

    for body in (
        {'action': 'tags', 'ids': [str(first.id)]},
        {'action': 'tags', 'ids': [str(first.id)], 'add_tag_ids': [str(foreign_tag.id)]},
        {'action': 'tags', 'ids': [str(first.id)], 'add_tag_ids': [str(sales.id)], 'remove_tag_ids': [str(sales.id)]},
    ):
        response = await api_client.post(URL, json=body, headers=headers)
        assert response.status_code == 400, body


@pytest.mark.asyncio
async def test_bulk_delete_and_restore_follow_author_or_admin(api_client, library):
    own = await library.recording(author=library.member)
    others = await library.recording(author=library.author)
    ids = [str(own.id), str(others.id)]

    response = await api_client.post(URL, json={'action': 'delete', 'ids': ids}, headers=library.h(library.member))
    assert response.json()['updated'] == [str(own.id)]
    assert _skipped(response) == {str(others.id): 'forbidden'}
    assert (await Recording.get(id=own.id)).deleted_at is not None
    assert (await Recording.get(id=others.id)).deleted_at is None

    # The admin deletes anything visible; an already deleted one is not found for `delete`.
    response = await api_client.post(URL, json={'action': 'delete', 'ids': ids}, headers=library.h(library.admin))
    assert response.json()['updated'] == [str(others.id)]
    assert _skipped(response) == {str(own.id): 'not_found'}

    # Restore works on deleted ones only; the member may restore only their own.
    response = await api_client.post(URL, json={'action': 'restore', 'ids': ids}, headers=library.h(library.member))
    assert response.json()['updated'] == [str(own.id)]
    assert _skipped(response) == {str(others.id): 'forbidden'}
    response = await api_client.post(URL, json={'action': 'restore', 'ids': ids}, headers=library.h(library.admin))
    assert response.json()['updated'] == [str(others.id)]
    assert await Recording.filter(deleted_at__isnull=True).count() == 2
    kinds = await RecordingEvent.filter(recording_id=others.id).order_by('created_at').values_list('kind', flat=True)
    assert list(kinds) == [RecordingEventKind.DELETED, RecordingEventKind.RESTORED]


@pytest.mark.asyncio
async def test_bulk_validates_the_request(api_client, library):
    recording = await library.recording()
    headers = library.h(library.member)
    for body in (
        {'action': 'delete', 'ids': []},
        {'action': 'delete', 'ids': [str(uuid4()) for _ in range(201)]},
        {'action': 'archive', 'ids': [str(recording.id)]},
        {'action': 'delete', 'ids': [str(recording.id)], 'extra': 1},
    ):
        response = await api_client.post(URL, json=body, headers=headers)
        assert response.status_code == 422, body


@pytest.mark.asyncio
async def test_bulk_realtime_is_per_recording_then_one_resync(api_client, library, websocket_fanout):
    small = [await library.recording() for _ in range(2)]
    large = [await library.recording() for _ in range(51)]
    socket = AsyncMock()
    key = f'{OrganizationWebSocketService.CHANNEL_NAME}/{library.org.id}'
    OrganizationWebSocketService.connections[key]['member'] = socket
    try:
        await api_client.post(
            URL, json={'action': 'delete', 'ids': [str(r.id) for r in small]}, headers=library.h(library.author)
        )
        await api_client.post(
            URL, json={'action': 'delete', 'ids': [str(r.id) for r in large]}, headers=library.h(library.author)
        )
    finally:
        OrganizationWebSocketService.connections.pop(key, None)
    messages = [json.loads(call.args[0]) for call in socket.send_text.await_args_list]
    assert [message['type'] for message in messages] == ['recording.deleted', 'recording.deleted', 'recordings.resync']
    assert set(messages[-1]['data']) == {'updated_at'}
