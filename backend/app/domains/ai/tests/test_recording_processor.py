import asyncio
import shutil

import pytest

from app.domains.ai.models import RecordingProcessing, RecordingResult, ResultStatus
from app.domains.ai.services.audio_segmenter import AudioSegmenter
from app.domains.ai.services.result_service import ResultService
from app.domains.ai.tests.conftest import AUDIO_MODEL, FakeSegmenter
from app.domains.ai.tests.fakes import error_reply
from app.domains.library.models import (
    ProjectSuggestionState,
    Recording,
    RecordingEvent,
    RecordingEventKind,
    RecordingStatus,
    TitleSource,
)

needs_ffmpeg = pytest.mark.skipif(not AudioSegmenter.is_available(), reason='ffmpeg/ffprobe not installed')


async def _tone(path, seconds: int) -> None:
    process = await asyncio.create_subprocess_exec(
        shutil.which('ffmpeg') or 'ffmpeg',
        '-nostdin',
        '-v',
        'error',
        '-f',
        'lavfi',
        '-i',
        f'sine=frequency=440:d={seconds}',
        '-c:a',
        'aac',
        str(path),
    )
    assert await process.wait() == 0


async def _events(recording: Recording) -> list[str]:
    return [event.kind for event in await RecordingEvent.filter(recording_id=recording.id).order_by('created_at')]


@needs_ffmpeg
@pytest.mark.asyncio
async def test_full_pipeline_on_real_audio(ai_team, fake_ai, tmp_path):
    source = tmp_path / 'meeting.m4a'
    await _tone(source, 130)
    project = await ai_team.project('Релиз 2.0')
    fake_ai.transcripts = ['Начинаем планирование.', 'Решили выпустить в пятницу.']
    fake_ai.classification = {'tags': ['релиз'], 'project': 'релиз 2.0', 'project_confidence': 0.9}
    recording = await ai_team.recording()

    await ai_team.processor(AudioSegmenter(), source).process(recording.id)

    stored = await Recording.get(id=recording.id)
    assert stored.status == RecordingStatus.TRANSCRIBED
    assert stored.progress == 100
    # 130 s at 60 s chunks: the 10 s tail joins the second chunk
    assert [(s['start_ms'], s['end_ms']) for s in stored.transcript_segments] == [(0, 60_000), (60_000, 130_000)]
    assert stored.transcript_text == 'Начинаем планирование.\nРешили выпустить в пятницу.'
    assert stored.transcription_model == AUDIO_MODEL
    assert stored.title == 'Планирование релиза'
    assert [tag.name for tag in await stored.tags.all()] == ['релиз']
    assert stored.suggested_project_id == project.id
    assert stored.project_suggestion_state == ProjectSuggestionState.PENDING
    audio = fake_ai.audio_requests[0]['messages'][-1]['content'][1]['input_audio']
    assert audio['format'] == 'mp3'
    assert fake_ai.audio_requests[0]['max_tokens'] >= 4096

    results = await RecordingResult.filter(recording_id=recording.id)
    assert [(r.title, r.status, r.created_by_id) for r in results] == [('Кратко', ResultStatus.QUEUED, None)]
    await ResultService.generate(results[0].id)
    done = await RecordingResult.get(id=results[0].id)
    assert (done.status, done.content) == (ResultStatus.DONE, '- главное')
    assert {'transcribed', 'renamed', 'tagged', 'result_created'} <= set(await _events(stored))


@pytest.mark.asyncio
async def test_failure_keeps_finished_segments_and_retry_resumes_without_duplicates(ai_team, fake_ai):
    recording = await ai_team.recording()
    segmenter = FakeSegmenter(duration_ms=180_000)
    fake_ai.transcripts = ['Первый.', error_reply(401, 'User not found')]

    await ai_team.processor(segmenter).process(recording.id)

    failed = await Recording.get(id=recording.id)
    assert failed.status == RecordingStatus.FAILED
    assert failed.error_code == 'auth'
    assert failed.error_message == 'Ключ OpenRouter не принят: проверьте его в настройках AI'
    assert failed.transcript_text == 'Первый.'
    assert (failed.segments_done, failed.segments_total) == (1, 3)

    fake_ai.transcripts = ['Второй.', 'Третий.']
    await ai_team.processor(segmenter).process(recording.id, force=True)

    stored = await Recording.get(id=recording.id)
    assert stored.status == RecordingStatus.TRANSCRIBED
    assert stored.transcript_text == 'Первый.\nВторой.\nТретий.'
    # Only the missing chunks were sent again.
    assert segmenter.cuts == [(0, 60_000), (60_000, 120_000), (60_000, 120_000), (120_000, 180_000)]
    assert len(fake_ai.audio_requests) == 4

    # A re-delivered task repeats nothing: no new requests, no second set of summaries.
    requests_before = len(fake_ai.audio_requests) + len(fake_ai.text_requests)
    await ai_team.processor(segmenter).process(recording.id)
    assert len(fake_ai.audio_requests) + len(fake_ai.text_requests) == requests_before
    assert await RecordingResult.filter(recording_id=recording.id).count() == 1


@pytest.mark.asyncio
async def test_crash_mid_transcription_resumes_from_the_last_saved_chunk(ai_team, fake_ai):
    recording = await ai_team.recording()
    segmenter = FakeSegmenter(duration_ms=180_000)

    async def crash(count: int) -> None:
        if count == 2:
            raise RuntimeError('worker killed')

    fake_ai.hooks.append(crash)
    fake_ai.transcripts = ['Первый.']
    await ai_team.processor(segmenter).process(recording.id)
    crashed = await Recording.get(id=recording.id)
    assert crashed.status == RecordingStatus.FAILED
    assert crashed.error_message == 'Не удалось обработать запись, попробуйте ещё раз'
    assert crashed.transcript_text == 'Первый.'

    fake_ai.hooks.clear()
    fake_ai.transcripts = ['Второй.', 'Третий.']
    await ai_team.processor(segmenter).process(recording.id)
    stored = await Recording.get(id=recording.id)
    assert stored.transcript_text == 'Первый.\nВторой.\nТретий.'
    assert [s['start_ms'] for s in stored.transcript_segments] == [0, 60_000, 120_000]


@pytest.mark.asyncio
async def test_user_rename_during_processing_wins(ai_team, fake_ai):
    recording = await ai_team.recording()

    async def rename(count: int) -> None:
        if count == 1:
            await Recording.filter(id=recording.id).update(title='Моё название', title_source=TitleSource.USER)

    fake_ai.hooks.append(rename)
    await ai_team.processor(FakeSegmenter(duration_ms=120_000)).process(recording.id)

    stored = await Recording.get(id=recording.id)
    assert stored.status == RecordingStatus.TRANSCRIBED
    assert (stored.title, stored.title_source) == ('Моё название', TitleSource.USER)
    assert RecordingEventKind.RENAMED not in await _events(stored)


@pytest.mark.asyncio
async def test_app_transcript_skips_transcription_but_runs_the_rest(ai_team, fake_ai):
    recording = await ai_team.recording(
        status=RecordingStatus.TRANSCRIBED,
        transcript_text='Готовый текст из приложения',
        transcript_segments=[{'start_ms': 0, 'end_ms': 5000, 'text': 'Готовый текст из приложения'}],
    )
    await ai_team.processor(FakeSegmenter(duration_ms=5000)).process(recording.id)

    stored = await Recording.get(id=recording.id)
    assert ai_team.downloads == []
    assert fake_ai.audio_requests == []
    assert stored.title == 'Планирование релиза'
    assert stored.transcript_text == 'Готовый текст из приложения'
    assert await RecordingResult.filter(recording_id=recording.id).count() == 1
    processing = await RecordingProcessing.get(recording_id=recording.id)
    assert processing.titled and processing.classified and processing.summarized


@pytest.mark.asyncio
async def test_auto_transcribe_off_waits_for_a_manual_request(ai_team, fake_ai):
    ai_team.settings.auto_transcribe = False
    await ai_team.settings.save()
    recording = await ai_team.recording()
    processor = ai_team.processor(FakeSegmenter(duration_ms=30_000))

    await processor.process(recording.id)
    assert (await Recording.get(id=recording.id)).status == RecordingStatus.QUEUED

    await processor.process(recording.id, force=True)
    assert (await Recording.get(id=recording.id)).status == RecordingStatus.TRANSCRIBED


@pytest.mark.asyncio
async def test_disabled_steps_are_skipped(ai_team, fake_ai):
    ai_team.settings.auto_title = False
    ai_team.settings.auto_tags = False
    ai_team.settings.auto_project = False
    await ai_team.settings.save()
    recording = await ai_team.recording(title='Исходное')
    await ai_team.processor(FakeSegmenter(duration_ms=30_000)).process(recording.id)
    stored = await Recording.get(id=recording.id)
    assert stored.title == 'Исходное'
    assert await stored.tags.all().count() == 0
    # Only the automatic summary was requested (by its own task, not run here).
    assert fake_ai.text_requests == []


@pytest.mark.asyncio
async def test_missing_configuration_fails_with_a_clear_message(ai_team, fake_ai):
    ai_team.settings.openrouter_api_key_encrypted = ''
    await ai_team.settings.save()
    recording = await ai_team.recording()
    await ai_team.processor(FakeSegmenter(duration_ms=30_000)).process(recording.id)
    stored = await Recording.get(id=recording.id)
    assert stored.status == RecordingStatus.FAILED
    assert stored.error_message == 'AI не настроен: администратор не добавил ключ OpenRouter'
    assert ai_team.downloads == []


@pytest.mark.asyncio
async def test_retranscribe_keeps_the_old_transcript_until_success(ai_team, fake_ai):
    old_segments = [{'start_ms': 0, 'end_ms': 120_000, 'text': 'Старый текст'}]
    recording = await ai_team.recording(
        status=RecordingStatus.TRANSCRIBED,
        transcript_text='Старый текст',
        transcript_segments=old_segments,
        transcription_model=AUDIO_MODEL,
    )
    processing, _ = await RecordingProcessing.get_or_create(
        recording_id=recording.id, titled=True, classified=True, summarized=True
    )
    processing.retranscribe_model = 'other/audio'
    await processing.save()
    seen_during: list[str] = []

    async def peek(count: int) -> None:
        seen_during.append((await Recording.get(id=recording.id)).transcript_text)

    fake_ai.hooks.append(peek)
    fake_ai.transcripts = ['Новый один.', error_reply(402, 'no credits')]
    segmenter = FakeSegmenter(duration_ms=120_000)
    await ai_team.processor(segmenter).process(recording.id)

    failed = await Recording.get(id=recording.id)
    assert failed.status == RecordingStatus.FAILED
    assert failed.transcript_text == 'Старый текст'
    assert failed.error_message == 'На счёте OpenRouter недостаточно средств'

    fake_ai.transcripts = ['Новый два.']
    await ai_team.processor(segmenter).process(recording.id, force=True)
    stored = await Recording.get(id=recording.id)
    assert stored.status == RecordingStatus.TRANSCRIBED
    assert stored.transcript_text == 'Новый один.\nНовый два.'
    assert stored.transcription_model == 'other/audio'
    assert fake_ai.audio_requests[-1]['model'] == 'other/audio'
    assert set(seen_during) == {'Старый текст'}
    processing = await RecordingProcessing.get(recording_id=recording.id)
    assert processing.retranscribe_model is None and processing.retranscribe_segments == []
    # The new transcript got a fresh title; tags and summaries were not repeated.
    assert stored.title == 'Планирование релиза'
    assert await RecordingResult.filter(recording_id=recording.id).count() == 0


@pytest.mark.asyncio
async def test_concurrent_runs_do_not_overlap(ai_team, fake_ai):
    recording = await ai_team.recording()
    segmenter = FakeSegmenter(duration_ms=30_000)
    await asyncio.gather(
        ai_team.processor(segmenter).process(recording.id), ai_team.processor(segmenter).process(recording.id)
    )
    assert len(fake_ai.audio_requests) == 1
    assert (await Recording.get(id=recording.id)).transcript_text == 'Речь.'
