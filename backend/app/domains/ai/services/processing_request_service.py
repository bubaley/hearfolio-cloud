from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.domains.ai.models import RecordingProcessing
from app.domains.ai.schemas import RetranscribeSchema
from app.domains.ai.services.organization_settings_service import OrganizationSettingsService
from app.domains.ai.services.task_kicker import PROCESS_RECORDING_TASK, AITaskKicker
from app.domains.library.models import Recording, RecordingStatus, UploadState
from app.domains.organization.models import Organization


class ProcessingRequestService:
    """User requests to (re)run the pipeline: «Повторить» and «Расшифровать заново». Anyone who sees the recording."""

    @staticmethod
    def require_audio(recording: Recording) -> None:
        if recording.upload_state != UploadState.UPLOADED:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Аудио ещё не загружено')

    @classmethod
    async def retry(cls, recording: Recording) -> Recording:
        """Resume a failed (or never started) processing from the last finished chunk."""
        cls.require_audio(recording)
        if recording.status not in (RecordingStatus.FAILED, RecordingStatus.QUEUED):
            raise AppException.from_attrs(ErrorCode.CONFLICT, 'Повторять нечего: запись уже обработана или в работе')
        await AITaskKicker.kick(PROCESS_RECORDING_TASK, str(recording.id), force=True)
        return recording

    @classmethod
    async def validate_retranscribe(cls, recording: Recording, data: RetranscribeSchema) -> str:
        cls.require_audio(recording)
        if recording.status == RecordingStatus.TRANSCRIBING:
            raise AppException.from_attrs(ErrorCode.CONFLICT, 'Расшифровка уже идёт')
        settings = await OrganizationSettingsService.ensure(await Organization.get(id=recording.organization_id))
        model = data.model or settings.transcription_default_model
        if not model:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Администратор не выбрал модель для расшифровки')
        if model not in (settings.transcription_models or []):
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Эта модель не разрешена в организации')
        if not settings.openrouter_api_key_encrypted:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'AI не настроен: нет ключа OpenRouter')
        return model

    @staticmethod
    async def retranscribe(recording: Recording, model: str) -> Recording:
        """Start a fresh transcript with `model`; the current one stays until the new one is complete."""
        processing, _ = await RecordingProcessing.get_or_create(recording_id=recording.id)
        processing.retranscribe_model = model
        processing.retranscribe_segments = []
        await processing.save(update_fields=['retranscribe_model', 'retranscribe_segments', 'updated_at'])
        await AITaskKicker.kick(PROCESS_RECORDING_TASK, str(recording.id), force=True)
        return recording
