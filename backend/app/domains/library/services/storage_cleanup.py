from uuid import UUID

from loguru import logger
from taskiq.kicker import AsyncKicker

from app.core.broker import broker
from app.core.services.s3_service import S3Error, get_s3_service
from app.core.settings import settings
from app.domains.library.models import Recording

DELETE_AUDIO_TASK = 'library.delete_audio'
# Keys per task message (one S3 batch delete each)
CLEANUP_BATCH_SIZE = 1000


class StorageCleanup:
    """
    Audio that outlives its rows: deleting an organization cascades its recordings in the database, so their S3
    objects (and unfinished multipart uploads) are collected first and removed by `library.delete_audio` tasks.
    """

    @staticmethod
    async def collect(organization_id: UUID) -> tuple[list[str], list[tuple[str, str]]]:
        """Audio keys and open multipart uploads `(key, upload_id)` of every recording of the organization."""
        rows: list[tuple[str, str | None]] = await Recording.filter(organization_id=organization_id).values_list(
            'audio_key', 'upload_id'
        )
        keys = [key for key, _ in rows if key]
        uploads = [(key, upload_id) for key, upload_id in rows if key and upload_id]
        return keys, uploads

    @classmethod
    async def enqueue(cls, keys: list[str], uploads: list[tuple[str, str]]) -> int:
        """Kick one task per batch; returns how many were enqueued."""
        kicked = 0
        for start in range(0, max(len(keys), len(uploads)), CLEANUP_BATCH_SIZE):
            batch_keys = keys[start : start + CLEANUP_BATCH_SIZE]
            batch_uploads = [list(upload) for upload in uploads[start : start + CLEANUP_BATCH_SIZE]]
            if await cls._kick(batch_keys, batch_uploads):
                kicked += 1
        return kicked

    @staticmethod
    async def _kick(keys: list[str], uploads: list[list[str]]) -> bool:
        task = broker.find_task(DELETE_AUDIO_TASK)
        try:
            if task is not None:
                await task.kiq(keys, uploads)
                return True
            if settings.testing:
                return False
            await AsyncKicker(task_name=DELETE_AUDIO_TASK, broker=broker, labels={}).kiq(keys, uploads)
            return True
        except Exception as e:
            logger.error('Could not enqueue deletion of {} audio objects: {}', len(keys), e)
            return False

    @staticmethod
    async def delete(keys: list[str], uploads: list[list[str]]) -> list[str]:
        """Task body: abort the open uploads, batch-delete the objects. Returns the keys that failed."""
        s3 = get_s3_service()
        for key, upload_id in uploads:
            try:
                await s3.abort_multipart_upload(key, upload_id)
            except S3Error as e:
                logger.info('Abort of upload {} skipped: {}', upload_id, e.__cause__)
        failed = await s3.delete_many(keys)
        if failed:
            logger.error('Could not delete {} audio objects, e.g. {}', len(failed), failed[:3])
        return failed
