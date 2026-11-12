from app.core.broker import broker
from app.domains.library.services.purge_service import PurgeService
from app.domains.library.services.storage_cleanup import DELETE_AUDIO_TASK, StorageCleanup


@broker.task(task_name='library.purge_deleted_recordings', schedule=[{'cron': '17 3 * * *'}])
async def purge_deleted_recordings() -> int:
    """Daily: delete recordings soft-deleted more than RECORDING_PURGE_AFTER_DAYS ago, with their audio."""
    return await PurgeService.purge_deleted_recordings()


@broker.task(task_name=DELETE_AUDIO_TASK)
async def delete_audio(keys: list[str], uploads: list[list[str]]) -> int:
    """Delete audio objects (and abort multipart uploads) of a deleted organization. Returns the failures."""
    return len(await StorageCleanup.delete(keys, uploads))
