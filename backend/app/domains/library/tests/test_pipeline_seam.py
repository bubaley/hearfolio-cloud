import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.broker import broker
from app.domains.library.models import (
    ProjectSuggestionState,
    Recording,
    RecordingEvent,
    RecordingEventKind,
    RecordingStatus,
    RecordingVisibility,
    Tag,
    TitleSource,
)
from app.domains.library.schemas import TranscriptSegmentSchema
from app.domains.library.services import pipeline as pipeline_module
from app.domains.library.services.purge_service import PurgeService
from app.domains.library.services.recording_service import RecordingService
from app.domains.library.tasks import purge_deleted_recordings
from app.domains.organization.services.organization_websocket_service import OrganizationWebSocketService


def _segment(start: int, end: int, text: str) -> TranscriptSegmentSchema:
    return TranscriptSegmentSchema(start_ms=start, end_ms=end, text=text)


@pytest.mark.asyncio
async def test_enqueue_kicks_a_registered_task_by_name(library, monkeypatch):
    recording = await library.recording()
    task = AsyncMock()
    monkeypatch.setattr(
        broker, 'find_task', lambda name: task if name == pipeline_module.PROCESS_RECORDING_TASK else None
    )
    assert await pipeline_module.RecordingPipeline.enqueue(recording) is True
    task.kiq.assert_awaited_once_with(str(recording.id))


@pytest.mark.asyncio
async def test_transcription_progress_and_resume(library):
    recording = await library.recording()
    await RecordingService.start_transcription(recording, model='openai/gpt-audio', segments_total=3, language='ru')
    assert recording.status == RecordingStatus.TRANSCRIBING

    await RecordingService.save_segments(recording, [_segment(0, 1000, 'Раз')], segments_done=1)
    # A crashed worker re-runs the first chunk: nothing is duplicated.
    fresh = await Recording.get(id=recording.id)
    await RecordingService.save_segments(fresh, [_segment(0, 1000, 'Раз')], segments_done=1)
    await RecordingService.save_segments(fresh, [_segment(1000, 2000, 'Два')], segments_done=2)
    stored = await Recording.get(id=recording.id)
    assert stored.progress == 67
    assert [segment['text'] for segment in stored.transcript_segments] == ['Раз', 'Два']
    assert stored.transcript_text == 'Раз\nДва'

    await RecordingService.set_failed(stored, code='provider_timeout', message='Сервис не ответил. Повторите позже.')
    stored = await Recording.get(id=recording.id)
    assert stored.status == RecordingStatus.FAILED and stored.transcript_text == 'Раз\nДва'

    await RecordingService.save_segments(stored, [_segment(2000, 3000, 'Три')], segments_done=3)
    await RecordingService.mark_transcribed(stored, model='openai/gpt-audio')
    stored = await Recording.get(id=recording.id)
    assert (stored.status, stored.progress, stored.error_message) == (RecordingStatus.TRANSCRIBED, 100, None)
    kinds = await RecordingEvent.filter(recording_id=recording.id).values_list('kind', flat=True)
    assert set(kinds) == {RecordingEventKind.FAILED, RecordingEventKind.TRANSCRIBED}
    assert await RecordingEvent.filter(recording_id=recording.id, actor_id=None).count() == 2


@pytest.mark.asyncio
async def test_set_transcript_replaces_it(library):
    recording = await library.recording(transcript='old')
    await RecordingService.set_transcript(recording, segments=[_segment(0, 10, 'new')], model='m2')
    stored = await Recording.get(id=recording.id)
    assert (stored.transcript_text, stored.transcription_model) == ('new', 'm2')


@pytest.mark.asyncio
async def test_ai_title_never_overwrites_a_user_title(library):
    recording = await library.recording(title='')
    assert await RecordingService.set_title_from_ai(recording, '  Планёрка   отдела ') is True
    assert (await Recording.get(id=recording.id)).title == 'Планёрка отдела'

    # The user renames while the pipeline is running; the stale instance still says `auto`.
    stale = await Recording.get(id=recording.id)
    await Recording.filter(id=recording.id).update(title='Моё', title_source=TitleSource.USER)
    assert await RecordingService.set_title_from_ai(stale, 'Другое') is False
    assert (await Recording.get(id=recording.id)).title == 'Моё'


@pytest.mark.asyncio
async def test_ai_tags_reuse_names_and_cap_at_five(library):
    existing = await Tag.create(organization=library.org, name='Продажи', name_key='продажи')
    recording = await library.recording()
    added = await RecordingService.apply_ai_tags(recording, ['продажи', 'Клиенты', 'клиенты', 'a', 'b', 'c', 'd', 'e'])
    assert [tag.name for tag in added] == ['Продажи', 'Клиенты', 'a', 'b', 'c']
    assert added[0].id == existing.id
    assert await recording.tags.all().count() == 5
    assert await RecordingService.apply_ai_tags(recording, ['Продажи']) == []
    assert await Tag.filter(organization=library.org).count() == 5


@pytest.mark.asyncio
async def test_project_suggestion(api_client, library):
    public = await library.project(name='Продажи')
    hidden = await library.project(private=True, members=(library.member,), name='Hidden')
    recording = await library.recording()
    # The author cannot see `hidden`: ignored.
    assert await RecordingService.suggest_project(recording, hidden) is False
    assert await RecordingService.suggest_project(recording, public) is True
    stored = await Recording.get(id=recording.id)
    assert stored.project_suggestion_state == ProjectSuggestionState.PENDING

    response = await api_client.post(
        f'/api/v1/recordings/{recording.id}/project-suggestion/accept', headers=library.h(library.member)
    )
    assert response.status_code == 200, response.text
    assert response.json()['project_id'] == str(public.id)
    assert response.json()['project_suggestion_state'] == 'accepted'
    # An answered suggestion is never re-offered.
    assert await RecordingService.suggest_project(await Recording.get(id=recording.id), public) is False

    other = await library.recording()
    await RecordingService.suggest_project(other, public)
    response = await api_client.post(
        f'/api/v1/recordings/{other.id}/project-suggestion/dismiss', headers=library.h(library.member)
    )
    assert response.json()['project_suggestion_state'] == 'dismissed'
    assert response.json()['project_id'] is None


@pytest.mark.asyncio
async def test_changes_publish_minimal_realtime_events(api_client, library, websocket_fanout):
    recording = await library.recording()
    member = AsyncMock()
    key = f'{OrganizationWebSocketService.CHANNEL_NAME}/{library.org.id}'
    OrganizationWebSocketService.connections[key]['member'] = member
    try:
        await api_client.patch(
            f'/api/v1/recordings/{recording.id}', json={'title': 'X'}, headers=library.h(library.member)
        )
        await api_client.delete(f'/api/v1/recordings/{recording.id}', headers=library.h(library.author))
    finally:
        OrganizationWebSocketService.connections.pop(key, None)
    messages = [json.loads(call.args[0]) for call in member.send_text.await_args_list]
    assert [message['type'] for message in messages] == ['recording.updated', 'recording.deleted']
    assert all(set(message['data']) == {'id', 'updated_at'} for message in messages)


@pytest.mark.asyncio
async def test_purge_deletes_old_tombstones_and_their_audio(library, s3):
    old = await library.recording()
    recent = await library.recording()
    alive = await library.recording()
    stuck = await library.recording(visibility=RecordingVisibility.PERSONAL)
    long_ago = datetime.now(UTC) - timedelta(days=31)
    await Recording.filter(id__in=[old.id, stuck.id]).update(deleted_at=long_ago)
    await Recording.filter(id=recent.id).update(deleted_at=datetime.now(UTC) - timedelta(days=2))

    def delete_object(Bucket, Key):
        if Key == stuck.audio_key:
            from botocore.exceptions import ClientError

            raise ClientError({'Error': {'Code': '500', 'Message': 'boom'}}, 'DeleteObject')
        return {}

    s3.delete_object.side_effect = delete_object
    assert await PurgeService.purge_deleted_recordings(batch_size=1) == 1
    assert set(await Recording.all().values_list('id', flat=True)) == {recent.id, alive.id, stuck.id}

    s3.delete_object.side_effect = None
    result = await (await purge_deleted_recordings.kiq()).wait_result(timeout=2)
    assert not result.is_err, result.error
    assert result.return_value == 1
    assert purge_deleted_recordings.labels['schedule'] == [{'cron': '17 3 * * *'}]
