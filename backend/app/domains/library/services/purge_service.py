from datetime import timedelta

from loguru import logger

from app.core.services.s3_service import S3Error, get_s3_service
from app.core.settings import settings
from app.core.utils.date_utils import utcnow
from app.domains.library.models import Recording

PURGE_BATCH_SIZE = 200


class PurgeService:
    @staticmethod
    async def purge_deleted_recordings(batch_size: int = PURGE_BATCH_SIZE) -> int:
        """
        Hard-delete recordings soft-deleted longer than the retention period, audio first. A recording whose
        audio cannot be deleted stays for the next run. Returns how many were purged.
        """
        cutoff = utcnow() - timedelta(days=settings.recording_purge_after_days)
        s3 = get_s3_service()
        purged = 0
        failed: set = set()
        while True:
            batch = (
                await Recording.filter(deleted_at__lt=cutoff)
                .exclude(id__in=list(failed))
                .order_by('deleted_at')
                .limit(batch_size)
            )
            if not batch:
                return purged
            for recording in batch:
                if recording.upload_id:
                    try:
                        await s3.abort_multipart_upload(recording.audio_key, recording.upload_id)
                    except S3Error as e:
                        # Already completed or expired by a bucket lifecycle rule: nothing to abort.
                        logger.info('Abort of upload {} skipped: {}', recording.upload_id, e.__cause__)
                try:
                    await s3.delete(recording.audio_key)
                except S3Error as e:
                    logger.warning('Could not delete audio of recording {}: {}', recording.id, e.__cause__)
                    failed.add(recording.id)
                    continue
                await recording.delete()
                purged += 1
