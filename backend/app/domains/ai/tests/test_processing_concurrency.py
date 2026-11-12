from datetime import timedelta

import pytest

from app.core.utils.date_utils import utcnow
from app.domains.ai.models import RecordingProcessing, RecordingResult, ResultStatus
from app.domains.ai.services.openrouter_client import AIErrorCode, AIProviderError
from app.domains.ai.services.processing_lock import LockUnavailableError, ProcessingLock
from app.domains.ai.services.processing_request_service import ProcessingRequestService
from app.domains.ai.services.recording_processor import RecordingProcessor
from app.domains.ai.services.result_service import ResultService
from app.domains.ai.services.task_kicker import PROCESS_RECORDING_TASK, AITaskKicker
from app.domains.ai.services.text_task_service import TextTaskService
from app.domains.ai.tests.conftest import TEXT_MODEL, FakeSegmenter
from app.domains.library.models import Recording, RecordingStatus


@pytest.mark.asyncio
async def test_retranscribe_requested_during_post_processing_runs_after_it(ai_team, fake_ai, monkeypatch):
    """A kick that finds the lock busy is not acked and lost: the holder runs again before it leaves."""
    recording = await ai_team.recording()
    processor = ai_team.processor(FakeSegmenter(90_000))
    kicked: list[tuple] = []

    async def kick(task_name, *args, **kwargs):
        if task_name != PROCESS_RECORDING_TASK:
            return True
        kicked.append((task_name, args, kwargs))
        # The worker picks the message up immediately, while the first run still holds the lock.
        await processor.process(recording.id, force=kwargs.get('force', False))
        return True

    monkeypatch.setattr(AITaskKicker, 'kick', staticmethod(kick))
    original = RecordingProcessor._post_process
    calls = 0

    async def post_process(self, recording_, settings, processing):
        nonlocal calls
        calls += 1
        if calls == 1:
            fresh = await Recording.get(id=recording.id)
            await ProcessingRequestService.retranscribe(fresh, 'other/audio')
        await original(self, recording_, settings, processing)

    monkeypatch.setattr(RecordingProcessor, '_post_process', post_process)
    fake_ai.transcripts = ['Первая.', 'Первая-2.', 'Вторая.', 'Вторая-2.']

    await processor.process(recording.id)

    assert kicked, 'retranscribe kicked the task'
    stored = await Recording.get(id=recording.id)
    assert stored.transcription_model == 'other/audio'
    assert stored.transcript_text == 'Вторая.\nВторая-2.'
    processing = await RecordingProcessing.get(recording_id=recording.id)
    assert processing.retranscribe_model is None
    assert len(fake_ai.audio_requests) == 4
    # Nothing left behind: the lock is free and no request is pending.
    lock = ProcessingLock(f'recording:{recording.id}')
    assert await lock.take_pending() is None
    assert await lock.acquire()
    await lock.release()


@pytest.mark.asyncio
async def test_busy_lock_marks_pending_and_holder_reruns(ai_team, fake_ai):
    recording = await ai_team.recording(status=RecordingStatus.FAILED)
    holder = ProcessingLock(f'recording:{recording.id}')
    assert await holder.acquire()
    processor = ai_team.processor(FakeSegmenter(30_000))

    await processor.process(recording.id, force=True)
    assert fake_ai.audio_requests == []
    assert await ProcessingLock(f'recording:{recording.id}').take_pending() is True
    # Put the marker back and let the "holder" finish like RecordingProcessor.process does.
    await holder.mark_pending(True)
    await holder.release()
    await processor.process(recording.id)
    assert (await Recording.get(id=recording.id)).status == RecordingStatus.TRANSCRIBED


@pytest.mark.asyncio
async def test_lock_failure_runs_nothing_and_reschedules(ai_team, fake_ai, monkeypatch):
    recording = await ai_team.recording()

    async def broken(self):
        raise LockUnavailableError('redis down')

    scheduled: list[tuple] = []

    async def kick_later(task_name, delay, *args, **kwargs):
        scheduled.append((task_name, delay, args, kwargs))
        return True

    monkeypatch.setattr(ProcessingLock, 'acquire', broken)
    monkeypatch.setattr(AITaskKicker, 'kick_later', staticmethod(kick_later))
    processor = ai_team.processor(FakeSegmenter(30_000))

    await processor.process(recording.id, force=True, attempt=2)
    assert fake_ai.audio_requests == []
    assert scheduled == [('ai.process_recording', 120, (str(recording.id),), {'force': True, 'attempt': 3})]

    scheduled.clear()
    await processor.process(recording.id, attempt=5)
    assert scheduled == []


@pytest.mark.asyncio
async def test_result_stuck_running_after_a_crash_is_taken_over_and_swept(ai_team, fake_ai, monkeypatch):
    recording = await ai_team.recording(status=RecordingStatus.TRANSCRIBED, transcript_text='Обсудили релиз.')
    long_ago = utcnow() - timedelta(hours=1)
    stuck = await RecordingResult.create(recording=recording, title='Кратко', prompt='p', model=TEXT_MODEL)
    fresh = await RecordingResult.create(recording=recording, title='Кратко', prompt='p', model=TEXT_MODEL)
    await RecordingResult.filter(id=stuck.id).update(status=ResultStatus.RUNNING, updated_at=long_ago)
    await RecordingResult.filter(id=fresh.id).update(status=ResultStatus.RUNNING, updated_at=utcnow())

    # A redelivered task takes over a stale `running` result, but never one a live worker is running.
    taken = await ResultService.generate(stuck.id)
    assert taken is not None and taken.status == ResultStatus.DONE
    assert await ResultService.generate(fresh.id) is None

    kicks: list[tuple] = []

    async def kick(task_name, *args, **kwargs):
        kicks.append((task_name, args))
        return True

    monkeypatch.setattr(AITaskKicker, 'kick', staticmethod(kick))
    await RecordingResult.filter(id=stuck.id).update(status=ResultStatus.RUNNING, updated_at=long_ago)
    assert await ResultService.requeue_stale() == 1
    assert (await RecordingResult.get(id=stuck.id)).status == ResultStatus.QUEUED
    assert (await RecordingResult.get(id=fresh.id)).status == ResultStatus.RUNNING
    assert kicks == [('ai.generate_result', (str(stuck.id),))]


@pytest.mark.asyncio
async def test_auto_summaries_are_not_duplicated_after_a_crash(ai_team, fake_ai):
    recording = await ai_team.recording(status=RecordingStatus.TRANSCRIBED, transcript_text='Обсудили релиз.')
    processor = ai_team.processor(FakeSegmenter(30_000))
    tasks = TextTaskService(None, TEXT_MODEL)  # ty: ignore[invalid-argument-type]
    # The first run created the results but crashed before marking `summarized`.
    await processor._auto_summaries(recording, ai_team.settings, tasks)
    await processor._auto_summaries(recording, ai_team.settings, tasks)
    assert await RecordingResult.filter(recording_id=recording.id, created_by_id=None).count() == 1


@pytest.mark.asyncio
async def test_failed_result_carries_a_machine_code(ai_team, monkeypatch):
    recording = await ai_team.recording(status=RecordingStatus.TRANSCRIBED, transcript_text='Обсудили релиз.')
    result = await RecordingResult.create(recording=recording, title='Кратко', prompt='p', model=TEXT_MODEL)

    async def summarize(self, *args, **kwargs):
        raise AIProviderError(AIErrorCode.PAYMENT)

    monkeypatch.setattr(TextTaskService, 'summarize', summarize)
    failed = await ResultService.generate(result.id)
    assert failed is not None
    assert (failed.status, failed.error_code) == (ResultStatus.FAILED, 'payment')
    assert failed.error_message == 'На счёте OpenRouter недостаточно средств'
