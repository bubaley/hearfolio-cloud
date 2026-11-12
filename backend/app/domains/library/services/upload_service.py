import math
import mimetypes
from datetime import timedelta
from uuid import UUID

from loguru import logger
from pydantic import BaseModel, ConfigDict
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.services.s3_service import S3Error, S3UploadedPart, get_s3_service
from app.core.settings import settings
from app.core.utils.date_utils import utcnow
from app.domains.library.models import (
    Project,
    Recording,
    RecordingEventKind,
    RecordingStatus,
    Tag,
    TitleSource,
    UploadState,
)
from app.domains.library.schemas import (
    RecordingCreateSchema,
    UploadCompleteSchema,
    UploadPartSchema,
    UploadPlanSchema,
)
from app.domains.library.services.realtime import LibraryRealtime
from app.domains.library.services.recording_service import RecordingService
from app.domains.organization.models import Organization
from app.domains.user.models import User

AUDIO_KEY_PREFIX = 'hearfolio'
S3_MIN_PART_SIZE = 5 * 1024 * 1024
S3_MAX_PARTS = 10_000


class RecordingCreateData(BaseModel):
    organization: Organization
    author: User
    data: RecordingCreateSchema
    project: Project | None
    tags: list[Tag]

    model_config = ConfigDict(arbitrary_types_allowed=True)


class UploadService:
    """
    Recordings are created before their audio: the app gets an upload plan (one presigned PUT below
    UPLOAD_MULTIPART_THRESHOLD_BYTES, S3 multipart above), uploads straight to S3 and calls `complete`.
    Only the author uploads.
    """

    # CREATE

    @staticmethod
    async def find_existing(organization: Organization, client_id: UUID) -> Recording | None:
        return await Recording.get_or_none(organization_id=organization.id, client_id=client_id)

    @staticmethod
    def validate_existing(recording: Recording, author: User) -> None:
        if recording.created_by_id != author.id:
            raise AppException.from_attrs(ErrorCode.CONFLICT, 'This client_id belongs to another recording')

    @staticmethod
    async def validate_create(
        organization: Organization, author: User, data: RecordingCreateSchema
    ) -> RecordingCreateData:
        if data.audio_size > settings.upload_max_bytes:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'The audio file is too large')
        project = None
        if data.project_id is not None:
            project = await RecordingService.validate_project(data.project_id, organization.id, author)
        tags = await RecordingService.validate_tags(data.tag_ids, organization.id) if data.tag_ids else []
        return RecordingCreateData(organization=organization, author=author, data=data, project=project, tags=tags)

    @staticmethod
    def audio_key(original_filename: str, mime: str) -> str:
        filename = original_filename
        if '.' not in filename.rsplit('/', 1)[-1]:
            filename = f'audio{mimetypes.guess_extension(mime.split(";")[0].strip()) or ""}'
        return get_s3_service().generate_key(filename, prefix=AUDIO_KEY_PREFIX)

    @classmethod
    async def create(cls, payload: RecordingCreateData) -> Recording:
        data = payload.data
        has_transcript = bool(data.transcript_text and data.transcript_text.strip())
        segments = [segment.model_dump() for segment in data.transcript_segments or []] if has_transcript else []
        title = ' '.join((data.title or '').split())
        recording = Recording(
            organization_id=payload.organization.id,
            client_id=data.client_id,
            created_by_id=payload.author.id,
            visibility=data.visibility,
            project_id=payload.project.id if payload.project else None,
            title=title,
            title_source=TitleSource.USER if title else TitleSource.AUTO,
            recorded_at=data.recorded_at,
            duration_ms=data.duration_ms,
            source=data.source,
            audio_key=cls.audio_key(data.original_filename, data.audio_mime),
            audio_size=data.audio_size,
            audio_mime=data.audio_mime,
            original_filename=data.original_filename,
            status=RecordingStatus.TRANSCRIBED if has_transcript else RecordingStatus.AWAITING_UPLOAD,
            progress=100 if has_transcript else 0,
            transcript_text=data.transcript_text.strip() if has_transcript and data.transcript_text else '',
            transcript_segments=segments,
            transcription_model=data.transcription_model if has_transcript else None,
            language=data.language,
        )
        if data.audio_size >= settings.upload_multipart_threshold_bytes:
            recording.upload_part_size = cls.part_size(data.audio_size)
            recording.upload_id = await get_s3_service().create_multipart_upload(recording.audio_key, data.audio_mime)
            recording.upload_state = UploadState.UPLOADING
        try:
            async with in_transaction():
                await recording.save()
                if payload.tags:
                    await recording.tags.add(*payload.tags)
                await RecordingService.record_event(
                    recording, RecordingEventKind.CREATED, payload.author, {'source': data.source}
                )
        except IntegrityError:
            # The same client_id was created concurrently: the first one wins.
            await cls._abort_quietly(recording)
            existing = await cls.find_existing(payload.organization, data.client_id)
            if existing is None:
                raise
            cls.validate_existing(existing, payload.author)
            return existing
        await LibraryRealtime.recording_updated(recording)
        return recording

    @staticmethod
    async def _abort_quietly(recording: Recording) -> None:
        if not recording.upload_id:
            return
        try:
            await get_s3_service().abort_multipart_upload(recording.audio_key, recording.upload_id)
        except S3Error as e:
            logger.warning('Could not abort multipart upload {}: {}', recording.audio_key, e)

    # PLANS

    @staticmethod
    def part_size(size: int) -> int:
        part_size = max(settings.upload_part_size_bytes, S3_MIN_PART_SIZE)
        return max(part_size, math.ceil(size / S3_MAX_PARTS))

    @staticmethod
    def parts_count(recording: Recording) -> int:
        return max(1, math.ceil(recording.audio_size / (recording.upload_part_size or recording.audio_size)))

    @classmethod
    async def plan(cls, recording: Recording, part_numbers: list[int] | None = None) -> UploadPlanSchema | None:
        """Fresh presigned URLs for what is left to upload; None when there is nothing to upload."""
        if recording.upload_state == UploadState.UPLOADED or recording.deleted_at is not None:
            return None
        expires_in = settings.upload_presign_expire_seconds
        expires_at = utcnow() + timedelta(seconds=expires_in)
        s3 = get_s3_service()
        if not recording.upload_id:
            url = await s3.presigned_put_url(recording.audio_key, recording.audio_mime, expires_in=expires_in)
            return UploadPlanSchema(
                method='single', url=url, headers={'Content-Type': recording.audio_mime}, expires_at=expires_at
            )
        count = cls.parts_count(recording)
        numbers = sorted(set(part_numbers)) if part_numbers else list(range(1, count + 1))
        if any(number < 1 or number > count for number in numbers):
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, f'Part numbers must be between 1 and {count}')
        parts = [
            UploadPartSchema(
                part_number=number,
                url=await s3.presigned_upload_part_url(
                    recording.audio_key, recording.upload_id, number, expires_in=expires_in
                ),
            )
            for number in numbers
        ]
        return UploadPlanSchema(
            method='multipart',
            upload_id=recording.upload_id,
            part_size=recording.upload_part_size,
            parts_count=count,
            parts=parts,
            expires_at=expires_at,
        )

    @staticmethod
    def validate_uploader(recording: Recording, actor: User) -> None:
        if recording.created_by_id != actor.id:
            raise AppException.from_attrs(ErrorCode.FORBIDDEN, 'Only the author uploads the audio')
        if recording.deleted_at is not None:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'The recording is deleted')

    @classmethod
    async def refresh_plan(cls, recording: Recording, actor: User, part_numbers: list[int] | None) -> UploadPlanSchema:
        cls.validate_uploader(recording, actor)
        if recording.upload_state == UploadState.FAILED:
            await cls._restart_upload(recording)
        plan = await cls.plan(recording, part_numbers)
        if plan is None:
            raise AppException.from_attrs(ErrorCode.CONFLICT, 'The audio is already uploaded')
        return plan

    # COMPLETE

    @classmethod
    async def complete(cls, recording: Recording, actor: User, data: UploadCompleteSchema) -> Recording:
        """Verify the object in S3 (exists, expected size), mark it uploaded and hand it to the pipeline."""
        cls.validate_uploader(recording, actor)
        if recording.upload_state == UploadState.UPLOADED:
            return recording
        s3 = get_s3_service()
        if recording.upload_id:
            parts = (
                [S3UploadedPart(part_number=part.part_number, etag=part.etag) for part in data.parts]
                if data.parts
                else await s3.list_parts(recording.audio_key, recording.upload_id)
            )
            if len({part.part_number for part in parts}) != cls.parts_count(recording):
                raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Not every part is uploaded yet')
            try:
                await s3.complete_multipart_upload(recording.audio_key, recording.upload_id, parts)
            except S3Error as e:
                logger.warning('Completing upload of recording {} failed: {}', recording.id, e.__cause__)
                raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Could not complete the upload') from e
        info = await s3.head_object(recording.audio_key)
        if info is None:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'The audio is not uploaded yet')
        if info.size != recording.audio_size:
            await cls._fail_upload(recording, f'Expected {recording.audio_size} bytes, got {info.size}')
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'The uploaded audio has an unexpected size')
        return await RecordingService.mark_uploaded(recording, actor)

    @classmethod
    async def _restart_upload(cls, recording: Recording) -> None:
        """A rejected upload starts over (a new multipart upload for large files)."""
        recording.upload_state = UploadState.PENDING
        if recording.audio_size >= settings.upload_multipart_threshold_bytes:
            recording.upload_part_size = cls.part_size(recording.audio_size)
            recording.upload_id = await get_s3_service().create_multipart_upload(
                recording.audio_key, recording.audio_mime
            )
            recording.upload_state = UploadState.UPLOADING
        recording.error_code = None
        recording.error_message = None
        recording.updated_at = utcnow()
        await recording.save(
            update_fields=['upload_state', 'upload_id', 'upload_part_size', 'error_code', 'error_message', 'updated_at']
        )

    @staticmethod
    async def _fail_upload(recording: Recording, reason: str) -> None:
        logger.warning('Upload of recording {} rejected: {}', recording.id, reason)
        recording.upload_state = UploadState.FAILED
        recording.upload_id = None
        recording.error_code = 'upload_size_mismatch'
        recording.error_message = 'Размер загруженного файла не совпадает с ожидаемым. Загрузите запись ещё раз.'
        recording.updated_at = utcnow()
        await recording.save(update_fields=['upload_state', 'upload_id', 'error_code', 'error_message', 'updated_at'])
        await LibraryRealtime.recording_updated(recording)
