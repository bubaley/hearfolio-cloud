import secrets
from datetime import timedelta
from uuid import UUID

from tortoise.expressions import F
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.services.s3_service import get_s3_service
from app.core.settings import settings
from app.core.utils.date_utils import as_utc, utcnow
from app.domains.library.models import Recording, RecordingEventKind, ShareLink, UploadState
from app.domains.library.schemas import AudioUrlSchema, PublicShareSchema, ShareLinkUpsertSchema
from app.domains.library.services.pipeline import RecordingPipeline
from app.domains.library.services.recording_service import RecordingService
from app.domains.user.models import User

TOKEN_BYTES = 24


class ShareLinkService:
    """
    One active link per recording; anyone who sees the recording manages it. Editing keeps the token, revoking
    makes the public page 404 (a later share issues a new token).
    """

    @staticmethod
    async def active(recording: Recording) -> ShareLink | None:
        return await ShareLink.filter(recording_id=recording.id, revoked_at__isnull=True).first()

    @classmethod
    async def upsert(cls, recording: Recording, data: ShareLinkUpsertSchema, actor: User) -> ShareLink:
        if data.expires_at is not None and as_utc(data.expires_at) <= utcnow():
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Expiry must be in the future')
        values = {
            'include_audio': data.include_audio,
            'include_transcript': data.include_transcript,
            'result_ids': [str(result_id) for result_id in dict.fromkeys(data.result_ids)],
            'expires_at': data.expires_at,
        }
        link = await cls.active(recording)
        async with in_transaction():
            if link is None:
                link = ShareLink(
                    recording_id=recording.id, token=secrets.token_urlsafe(TOKEN_BYTES), created_by_id=actor.id
                )
                link.update_from_dict(values)
                await link.save()
                await RecordingService.record_event(recording, RecordingEventKind.SHARED, actor)
            else:
                link.update_from_dict(values)
                await link.save(update_fields=[*values, 'updated_at'])
        return link

    @classmethod
    async def revoke(cls, recording: Recording, actor: User) -> None:
        link = await cls.active(recording)
        if link is None:
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, 'The recording has no active link')
        link.revoked_at = utcnow()
        async with in_transaction():
            await link.save(update_fields=['revoked_at', 'updated_at'])
            await RecordingService.record_event(recording, RecordingEventKind.UNSHARED, actor)

    # PUBLIC

    @staticmethod
    async def get_public(token: str) -> ShareLink:
        """The link behind a public token: 404 when unknown, revoked, expired or the recording is deleted."""
        link = await ShareLink.filter(token=token, revoked_at__isnull=True).select_related('recording').first()
        if (
            link is None
            or (link.expires_at is not None and as_utc(link.expires_at) <= utcnow())
            or link.recording.deleted_at is not None
        ):
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, 'Not found')
        return link

    @classmethod
    async def open_public(cls, link: ShareLink) -> PublicShareSchema:
        recording: Recording = link.recording
        await ShareLink.filter(id=link.id).update(views=F('views') + 1)
        audio = None
        if link.include_audio and recording.upload_state == UploadState.UPLOADED:
            expires_in = settings.share_audio_presign_expire_seconds
            url = await get_s3_service().presigned_get_url(recording.audio_key, expires_in=expires_in)
            audio = AudioUrlSchema(url=url, expires_at=utcnow() + timedelta(seconds=expires_in))
        result_ids = [UUID(str(result_id)) for result_id in link.result_ids or []]
        return PublicShareSchema(
            title=recording.title,
            recorded_at=recording.recorded_at,
            duration_ms=recording.duration_ms,
            language=recording.language,
            audio=audio,
            transcript_text=recording.transcript_text if link.include_transcript else None,
            transcript_segments=recording.transcript_segments if link.include_transcript else None,
            results=await RecordingPipeline.shared_results(recording, result_ids),
        )
