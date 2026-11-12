from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from loguru import logger
from pydantic import BaseModel, ConfigDict
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.utils.date_utils import utcnow
from app.domains.ai.models import OrganizationSettings, RecordingResult, ResultStatus, SummaryTemplate
from app.domains.ai.schemas import RecordingResultsCreateSchema
from app.domains.ai.services.openrouter_client import AIErrorCode, AIProviderError
from app.domains.ai.services.organization_settings_service import OrganizationSettingsService
from app.domains.ai.services.task_kicker import GENERATE_RESULT_TASK, AITaskKicker
from app.domains.ai.services.text_task_service import TextTaskService
from app.domains.library.models import Recording, RecordingEventKind, RecordingStatus
from app.domains.library.services.recording_service import RecordingService
from app.domains.organization.models import Organization
from app.domains.organization.services.organization_service import OrganizationService
from app.domains.organization.services.organization_websocket_service import OrganizationWebSocketService
from app.domains.user.models import User

RESULT_UPDATED = 'result.updated'
CUSTOM_PROMPT_TITLE = 'Свой запрос'
# A summary is one model call; a result `running` longer than this lost its worker.
RESULT_STALE_AFTER = timedelta(minutes=15)


class ResultRequest(BaseModel):
    """A validated request: what to generate for which recording with which model."""

    recording: Recording
    templates: list[SummaryTemplate]
    custom_prompt: str | None
    model: str

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ResultService:
    """Summaries (`RecordingResult`): request, generate in a task, regenerate, delete, share."""

    @staticmethod
    async def notify(result: RecordingResult, organization_id: UUID, *, deleted: bool = False) -> None:
        """`result.updated` with a minimal payload; clients refetch through the visibility-checked API."""
        try:
            await OrganizationWebSocketService.notify(
                organization_id,
                RESULT_UPDATED,
                {
                    'id': result.id,
                    'recording_id': result.recording_id,
                    'status': result.status,
                    'deleted': deleted,
                    'updated_at': result.updated_at,
                },
            )
        except Exception as e:
            logger.warning('Could not publish {} for result {}: {}', RESULT_UPDATED, result.id, e)

    @staticmethod
    def require_transcript(recording: Recording) -> None:
        if recording.status != RecordingStatus.TRANSCRIBED or not recording.transcript_text.strip():
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Саммари можно сделать после расшифровки')

    @staticmethod
    def resolve_model(settings: OrganizationSettings, model: str | None) -> str:
        allowed = list(settings.summary_models or [])
        chosen = model or settings.summary_default_model
        if not chosen:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Администратор не выбрал модель для саммари')
        if chosen not in allowed:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Эта модель не разрешена в организации')
        if not settings.openrouter_api_key_encrypted:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'AI не настроен: нет ключа OpenRouter')
        return chosen

    @classmethod
    async def validate_create(cls, recording: Recording, data: RecordingResultsCreateSchema) -> ResultRequest:
        cls.require_transcript(recording)
        custom_prompt = data.custom_prompt or None
        template_ids = list(dict.fromkeys(data.template_ids))
        if not template_ids and not custom_prompt:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Выберите шаблон или напишите свой запрос')
        templates = await SummaryTemplate.filter(organization_id=recording.organization_id, id__in=template_ids)
        if len(templates) != len(template_ids):
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Шаблон не найден')
        templates.sort(key=lambda template: template_ids.index(template.id))
        organization = await Organization.get(id=recording.organization_id)
        settings = await OrganizationSettingsService.ensure(organization)
        return ResultRequest(
            recording=recording,
            templates=templates,
            custom_prompt=custom_prompt,
            model=cls.resolve_model(settings, data.model),
        )

    @classmethod
    async def create(cls, request: ResultRequest, actor: User | None) -> list[RecordingResult]:
        """One queued result per template (plus the custom prompt), each generated by its own task."""
        recording = request.recording
        specs: list[tuple[SummaryTemplate | None, str, str]] = [
            (template, template.name, template.prompt) for template in request.templates
        ]
        if request.custom_prompt:
            specs.append((None, CUSTOM_PROMPT_TITLE, request.custom_prompt))
        results: list[RecordingResult] = []
        async with in_transaction():
            for template, title, prompt in specs:
                result = await RecordingResult.create(
                    recording_id=recording.id,
                    template_id=template.id if template else None,
                    title=title,
                    prompt=prompt,
                    model=request.model,
                    created_by_id=actor.id if actor else None,
                )
                await RecordingService.record_event(
                    recording, RecordingEventKind.RESULT_CREATED, actor, {'result_id': result.id, 'title': title}
                )
                results.append(result)
        await cls.after_change(recording, results)
        for result in results:
            await AITaskKicker.kick(GENERATE_RESULT_TASK, str(result.id))
        return results

    @classmethod
    async def after_change(cls, recording: Recording, results: list[RecordingResult]) -> None:
        await RecordingService.touch_for_result(recording)
        for result in results:
            await cls.notify(result, recording.organization_id)

    @classmethod
    async def regenerate(cls, result: RecordingResult, actor: User) -> RecordingResult:
        """A new result with the same prompt snapshot and model; the old one stays until deleted."""
        recording = await Recording.get(id=result.recording_id)
        cls.require_transcript(recording)
        settings = await OrganizationSettingsService.ensure(await Organization.get(id=recording.organization_id))
        model = cls.resolve_model(settings, result.model if result.model in (settings.summary_models or []) else None)
        async with in_transaction():
            new = await RecordingResult.create(
                recording_id=recording.id,
                template_id=result.template_id,
                title=result.title,
                prompt=result.prompt,
                model=model,
                created_by_id=actor.id,
            )
            await RecordingService.record_event(
                recording, RecordingEventKind.RESULT_CREATED, actor, {'result_id': new.id, 'title': new.title}
            )
        await cls.after_change(recording, [new])
        await AITaskKicker.kick(GENERATE_RESULT_TASK, str(new.id))
        return new

    @staticmethod
    async def validate_delete(result: RecordingResult, actor: User) -> Recording:
        """Own results; automatic ones (no creator) also by the recording's author; anything by an org admin."""
        recording = await Recording.get(id=result.recording_id)
        if result.created_by_id == actor.id:
            return recording
        if result.created_by_id is None and recording.created_by_id == actor.id:
            return recording
        if await OrganizationService.is_admin(actor, recording.organization_id):
            return recording
        raise AppException.from_attrs(ErrorCode.FORBIDDEN, 'Удалить саммари может его автор или администратор')

    @classmethod
    async def delete(cls, result: RecordingResult, actor: User) -> None:
        recording = await cls.validate_delete(result, actor)
        await result.delete()
        await RecordingService.touch_for_result(recording)
        await cls.notify(result, recording.organization_id, deleted=True)

    @classmethod
    async def generate(cls, result_id: UUID) -> RecordingResult | None:
        """
        Task body: queued → running → done/failed. A result someone else is running is left alone, unless it has
        been `running` longer than RESULT_STALE_AFTER (its worker crashed): then this run takes it over.
        """
        now = utcnow()
        claimable = Q(status=ResultStatus.QUEUED) | Q(
            status=ResultStatus.RUNNING, updated_at__lt=now - RESULT_STALE_AFTER
        )
        taken = await RecordingResult.filter(claimable, id=result_id).update(
            status=ResultStatus.RUNNING, updated_at=now
        )
        if not taken:
            return None
        result = await RecordingResult.get(id=result_id)
        recording = await Recording.get(id=result.recording_id)
        await cls.after_change(recording, [result])
        try:
            settings = await OrganizationSettingsService.ensure(await Organization.get(id=recording.organization_id))
            async with OrganizationSettingsService.build_client(settings, max_attempts=2) as client:
                content = await TextTaskService(client, result.model).summarize(
                    recording.transcript_text, result.prompt, title=recording.title or None
                )
            result.content = content
            result.status = ResultStatus.DONE
            result.error_code = None
            result.error_message = None
        except AIProviderError as error:
            logger.warning('Result {} failed: {} {}', result.id, error.code, error.detail)
            result.status = ResultStatus.FAILED
            result.error_code = str(error.code)
            result.error_message = error.message
        except Exception:
            logger.exception('Result {} failed unexpectedly', result.id)
            result.status = ResultStatus.FAILED
            result.error_code = AIErrorCode.INTERNAL
            result.error_message = 'Не удалось сделать саммари, попробуйте ещё раз'
        await result.save(update_fields=['content', 'status', 'error_code', 'error_message', 'updated_at'])
        await cls.after_change(recording, [result])
        return result

    @staticmethod
    async def result_ids_of(recording: Recording, result_ids: list[UUID]) -> set[UUID]:
        """Seam for share links: which of `result_ids` are results of the recording."""
        ids = await RecordingResult.filter(recording_id=recording.id, id__in=result_ids).values_list('id', flat=True)
        return set(cast(list[UUID], ids))

    @staticmethod
    async def shared_results(recording: Recording, result_ids: list[UUID]) -> list[dict[str, Any]]:
        """Provider for public share links: finished results among `result_ids`, oldest first."""
        results = await RecordingResult.filter(
            recording_id=recording.id, id__in=result_ids, status=ResultStatus.DONE
        ).order_by('created_at')
        return [
            {
                'id': str(result.id),
                'title': result.title,
                'content': result.content,
                'model': result.model,
                'created_at': result.created_at.isoformat(),
            }
            for result in results
        ]

    @staticmethod
    async def requeue_stale(limit: int = 500) -> int:
        """Periodic: results stuck in `running` (a crashed worker) go back to `queued` and get a new task."""
        now = utcnow()
        stale_ids = (
            await RecordingResult.filter(status=ResultStatus.RUNNING, updated_at__lt=now - RESULT_STALE_AFTER)
            .limit(limit)
            .values_list('id', flat=True)
        )
        requeued = 0
        for result_id in stale_ids:
            if await RecordingResult.filter(
                id=result_id, status=ResultStatus.RUNNING, updated_at__lt=now - RESULT_STALE_AFTER
            ).update(status=ResultStatus.QUEUED, updated_at=now):
                requeued += 1
                await AITaskKicker.kick(GENERATE_RESULT_TASK, str(result_id))
        if requeued:
            logger.warning('Requeued {} stale summaries', requeued)
        return requeued
