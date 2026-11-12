from uuid import UUID

from app.core.broker import broker
from app.domains.ai.services.recording_processor import RecordingProcessor
from app.domains.ai.services.result_service import ResultService
from app.domains.ai.services.task_kicker import GENERATE_RESULT_TASK, PROCESS_RECORDING_TASK


@broker.task(task_name=PROCESS_RECORDING_TASK)
async def process_recording(recording_id: str, force: bool = False, attempt: int = 0) -> None:
    """Transcribe (resumable), then title, tags + project suggestion and automatic summaries per the settings."""
    await RecordingProcessor().process(UUID(recording_id), force=force, attempt=attempt)


@broker.task(task_name=GENERATE_RESULT_TASK)
async def generate_result(result_id: str) -> None:
    """Generate one queued summary."""
    await ResultService.generate(UUID(result_id))


@broker.task(task_name='ai.requeue_stale_results', schedule=[{'cron': '*/5 * * * *'}])
async def requeue_stale_results() -> int:
    """Every 5 minutes: summaries stuck in `running` after a worker crash are queued again."""
    return await ResultService.requeue_stale()
