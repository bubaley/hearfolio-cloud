import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger

from app.core.services.s3_service import get_s3_service
from app.domains.ai.models import OrganizationSettings, RecordingProcessing, RecordingResult, ResultStatus
from app.domains.ai.services.audio_segmenter import AudioProcessingError, AudioSegmenter, SegmentRange
from app.domains.ai.services.model_catalog_service import ModelCatalogService
from app.domains.ai.services.openrouter_client import AIErrorCode, AIProviderError
from app.domains.ai.services.organization_settings_service import OrganizationSettingsService
from app.domains.ai.services.processing_lock import ProcessingLock
from app.domains.ai.services.result_service import ResultRequest, ResultService
from app.domains.ai.services.summary_template_service import SummaryTemplateService
from app.domains.ai.services.task_kicker import GENERATE_RESULT_TASK, AITaskKicker
from app.domains.ai.services.text_task_service import TextTaskService
from app.domains.ai.services.transcription_engine import (
    SegmentSink,
    TranscribedSegment,
    TranscriptionEngine,
    TranscriptionError,
)
from app.domains.library.models import Recording, RecordingStatus, Tag, TitleSource, UploadState
from app.domains.library.schemas import TranscriptSegmentSchema
from app.domains.library.services.recording_service import RecordingService
from app.domains.library.services.visibility import LibraryVisibility
from app.domains.organization.models import Organization
from app.domains.user.models import User

# (recording, target file) -> the audio is written to `target`
AudioDownloader = Callable[[Recording, Path], Awaitable[None]]

# A transcript shorter than this (ms of audio left) is treated as complete.
RESUME_TOLERANCE_MS = 1000
CLASSIFY_TAG_CONTEXT = 300


class ProcessingFailure(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


async def download_from_s3(recording: Recording, target: Path) -> None:
    service = get_s3_service()
    try:
        await asyncio.to_thread(service.client.download_file, service.bucket, recording.audio_key, str(target))
    except Exception as e:
        logger.warning('Download of {} failed: {}', recording.audio_key, e)
        raise ProcessingFailure('storage', 'Не удалось получить аудио из хранилища') from e


def _segment_dicts(segments: list[Any]) -> list[dict[str, Any]]:
    return [segment for segment in segments or [] if isinstance(segment, dict)]


def _last_end(segments: list[dict[str, Any]]) -> int:
    return max((int(segment.get('end_ms', 0)) for segment in segments), default=0)


class RecordingProcessor:
    """
    The `ai.process_recording` pipeline: transcribe (resuming after the last saved chunk), then title, tags +
    project suggestion and automatic summaries, each step at most once (`RecordingProcessing` flags). A requested
    re-transcription collects its chunks in `RecordingProcessing` and replaces the transcript only on success.
    Writes go through `RecordingService` (docs/pipeline-seam.md).
    """

    def __init__(self, *, segmenter: AudioSegmenter | None = None, download: AudioDownloader = download_from_s3):
        self.segmenter = segmenter or AudioSegmenter()
        self.download = download

    async def process(self, recording_id: UUID, *, force: bool = False) -> None:
        lock = ProcessingLock(f'recording:{recording_id}')
        if not await lock.acquire():
            logger.info('Recording {} is already being processed', recording_id)
            return
        try:
            await self._process(recording_id, force=force, lock=lock)
        finally:
            await lock.release()

    async def _process(self, recording_id: UUID, *, force: bool, lock: ProcessingLock) -> None:
        recording = await Recording.get_or_none(id=recording_id)
        if recording is None or recording.deleted_at is not None or recording.upload_state != UploadState.UPLOADED:
            return
        settings = await OrganizationSettingsService.ensure(await Organization.get(id=recording.organization_id))
        processing, _ = await RecordingProcessing.get_or_create(recording_id=recording.id)
        try:
            if processing.retranscribe_model:
                await self._retranscribe(recording, settings, processing, lock)
            elif recording.status != RecordingStatus.TRANSCRIBED:
                if not settings.auto_transcribe and not force:
                    return
                await self._transcribe(recording, settings, lock)
        except ProcessingFailure as failure:
            await RecordingService.set_failed(recording, code=failure.code, message=failure.message)
            return
        except Exception:
            logger.exception('Processing of recording {} failed', recording.id)
            await RecordingService.set_failed(
                recording, code='internal', message='Не удалось обработать запись, попробуйте ещё раз'
            )
            return
        if recording.status == RecordingStatus.TRANSCRIBED:
            await self._post_process(recording, settings, processing)
        await self._kick_queued_results(recording)

    # TRANSCRIPTION

    def _transcription_model(self, settings: OrganizationSettings, model: str | None) -> str:
        if not settings.openrouter_api_key_encrypted:
            raise ProcessingFailure(
                AIErrorCode.NOT_CONFIGURED, 'AI не настроен: администратор не добавил ключ OpenRouter'
            )
        if not model:
            raise ProcessingFailure(AIErrorCode.NOT_CONFIGURED, 'AI не настроен: не выбрана модель для расшифровки')
        return model

    async def _transcribe(self, recording: Recording, settings: OrganizationSettings, lock: ProcessingLock) -> None:
        saved = _segment_dicts(recording.transcript_segments)
        # A resumed run keeps the model that produced the saved chunks.
        model = self._transcription_model(
            settings, recording.transcription_model if saved else settings.transcription_default_model
        )

        async def save(segment: TranscribedSegment, done: int, total: int) -> None:
            await RecordingService.save_segments(
                recording,
                [TranscriptSegmentSchema(start_ms=segment.start_ms, end_ms=segment.end_ms, text=segment.text)],
                segments_done=done,
                segments_total=total,
            )
            await lock.extend()

        await self._run(recording, settings, model, saved, save)
        await RecordingService.mark_transcribed(recording, model=model)

    async def _retranscribe(
        self,
        recording: Recording,
        settings: OrganizationSettings,
        processing: RecordingProcessing,
        lock: ProcessingLock,
    ) -> None:
        model = self._transcription_model(settings, processing.retranscribe_model)
        saved = _segment_dicts(processing.retranscribe_segments)

        async def save(segment: TranscribedSegment, done: int, total: int) -> None:
            processing.retranscribe_segments = [
                *_segment_dicts(processing.retranscribe_segments),
                {'start_ms': segment.start_ms, 'end_ms': segment.end_ms, 'text': segment.text},
            ]
            await processing.save(update_fields=['retranscribe_segments', 'updated_at'])
            await RecordingService.update_progress(recording, segments_done=done, segments_total=total)
            await lock.extend()

        await self._run(recording, settings, model, saved, save)
        segments = [TranscriptSegmentSchema(**segment) for segment in _segment_dicts(processing.retranscribe_segments)]
        await RecordingService.set_transcript(recording, segments=segments, model=model)
        processing.retranscribe_model = None
        processing.retranscribe_segments = []
        # The new transcript gets a fresh title (unless renamed by a user); tags and summaries stay.
        processing.titled = False
        await processing.save(update_fields=['retranscribe_model', 'retranscribe_segments', 'titled', 'updated_at'])

    async def _run(
        self,
        recording: Recording,
        settings: OrganizationSettings,
        model: str,
        saved: list[dict[str, Any]],
        save: SegmentSink,
    ) -> None:
        """Transcribe the audio after the end of `saved` chunk by chunk; `save` persists each finished chunk."""
        language = None if settings.language == 'auto' else settings.language
        with AudioSegmenter.workspace() as work_dir:
            source = work_dir / 'source'
            await self.download(recording, source)
            try:
                duration_ms = await self.segmenter.probe_duration_ms(source)
                resume_from = _last_end(saved)
                remaining = AudioSegmenter.plan(max(duration_ms - resume_from, 0), settings.segment_seconds)
                if duration_ms - resume_from < RESUME_TOLERANCE_MS:
                    remaining = []
                segments = [
                    SegmentRange(len(saved) + item.index, item.start_ms + resume_from, item.end_ms + resume_from)
                    for item in remaining
                ]
                await RecordingService.start_transcription(
                    recording, model=model, segments_total=len(saved) + len(segments), language=language
                )
                if not segments:
                    return
                mode = await ModelCatalogService.transcription_mode(settings, model)
                async with OrganizationSettingsService.build_client(settings, max_attempts=2) as client:
                    engine = TranscriptionEngine(client, self.segmenter, model=model, language=language, mode=mode)
                    await engine.transcribe(source, work_dir, segments=segments, on_segment=save)
            except TranscriptionError as error:
                raise ProcessingFailure(error.code, error.message) from error
            except AIProviderError as error:
                raise ProcessingFailure(error.code, error.message) from error
            except AudioProcessingError as error:
                logger.warning('Audio processing of {} failed: {}', recording.id, error.detail)
                raise ProcessingFailure('audio', error.message) from error

    # AFTER TRANSCRIPTION

    async def _post_process(
        self, recording: Recording, settings: OrganizationSettings, processing: RecordingProcessing
    ) -> None:
        """Title, tags + project, automatic summaries. A failed step is logged and left for the next run."""
        transcript = recording.transcript_text.strip()
        model = settings.summary_default_model
        if not transcript or not model or not settings.openrouter_api_key_encrypted:
            return
        steps = []
        if not processing.titled:
            steps.append(('titled', self._title))
        if not processing.classified:
            steps.append(('classified', self._classify))
        if not processing.summarized:
            steps.append(('summarized', self._auto_summaries))
        if not steps:
            return
        async with OrganizationSettingsService.build_client(settings, max_attempts=2) as client:
            tasks = TextTaskService(client, model)
            for flag, step in steps:
                try:
                    await step(recording, settings, tasks)
                except AIProviderError as error:
                    logger.warning(
                        'Step {} of recording {} failed: {} {}', flag, recording.id, error.code, error.detail
                    )
                    continue
                except Exception:
                    logger.exception('Step {} of recording {} failed', flag, recording.id)
                    continue
                setattr(processing, flag, True)
                await processing.save(update_fields=[flag, 'updated_at'])

    async def _title(self, recording: Recording, settings: OrganizationSettings, tasks: TextTaskService) -> None:
        if not settings.auto_title or recording.title_source == TitleSource.USER:
            return
        title = await tasks.generate_title(recording.transcript_text)
        if title:
            await RecordingService.set_title_from_ai(recording, title)

    async def _classify(self, recording: Recording, settings: OrganizationSettings, tasks: TextTaskService) -> None:
        if not settings.auto_tags and not settings.auto_project:
            return
        tag_names = (
            await Tag.filter(organization_id=recording.organization_id)
            .limit(CLASSIFY_TAG_CONTEXT)
            .values_list('name', flat=True)
        )
        author = await User.get_or_none(id=recording.created_by_id) if recording.created_by_id else None
        projects = []
        if settings.auto_project and author is not None and recording.project_id is None:
            projects = await LibraryVisibility.projects(author, recording.organization_id).filter(
                archived_at__isnull=True
            )
        result = await tasks.classify(
            recording.transcript_text, [str(name) for name in tag_names], [project.name for project in projects]
        )
        if settings.auto_tags and result.tags:
            await RecordingService.apply_ai_tags(recording, result.tags)
        if settings.auto_project and result.project:
            project = next((project for project in projects if project.name == result.project), None)
            if project is not None:
                await RecordingService.suggest_project(recording, project)

    async def _auto_summaries(
        self, recording: Recording, settings: OrganizationSettings, tasks: TextTaskService
    ) -> None:
        templates = await SummaryTemplateService.auto_templates(recording.organization_id)
        model = settings.summary_default_model
        if not templates or not model:
            return
        await ResultService.create(
            ResultRequest(recording=recording, templates=templates, custom_prompt=None, model=model), actor=None
        )

    async def _kick_queued_results(self, recording: Recording) -> None:
        """Results whose task was lost (a crash between creating and enqueueing) get another chance."""
        for result_id in await RecordingResult.filter(
            recording_id=recording.id, status=ResultStatus.QUEUED
        ).values_list('id', flat=True):
            await AITaskKicker.kick(GENERATE_RESULT_TASK, str(result_id))
