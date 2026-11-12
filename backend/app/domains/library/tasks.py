from app.core.broker import broker
from app.domains.library.services.purge_service import PurgeService


@broker.task(task_name='library.purge_deleted_recordings', schedule=[{'cron': '17 3 * * *'}])
async def purge_deleted_recordings() -> int:
    """Daily: delete recordings soft-deleted more than RECORDING_PURGE_AFTER_DAYS ago, with their audio."""
    return await PurgeService.purge_deleted_recordings()
