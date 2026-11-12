from datetime import timedelta
from typing import Any

from loguru import logger
from taskiq.kicker import AsyncKicker

from app.core.broker import broker, redis_schedule_source
from app.core.settings import settings
from app.core.utils.date_utils import utcnow
from app.domains.library.services.pipeline import PROCESS_RECORDING_TASK

__all__ = ('GENERATE_RESULT_TASK', 'PROCESS_RECORDING_TASK', 'AITaskKicker')

GENERATE_RESULT_TASK = 'ai.generate_result'


class AITaskKicker:
    """
    Kicks ai tasks by name, like `RecordingPipeline.enqueue`: the API process does not import `ai/tasks.py` (the
    worker discovers it), so views never pull the pipeline code in, and tests run nothing they did not register.
    """

    @staticmethod
    async def kick(task_name: str, *args: Any, **kwargs: Any) -> bool:
        task = broker.find_task(task_name)
        try:
            if task is not None:
                await task.kiq(*args, **kwargs)
                return True
            if settings.testing:
                return False
            await AsyncKicker(task_name=task_name, broker=broker, labels={}).kiq(*args, **kwargs)
            return True
        except Exception as e:
            logger.warning('Could not enqueue {} {}: {}', task_name, args, e)
            return False

    @staticmethod
    async def kick_later(task_name: str, delay_seconds: float, *args: Any, **kwargs: Any) -> bool:
        """Run the task once after `delay_seconds` (Redis schedule source; needs the taskiq scheduler)."""
        if settings.testing:
            return False
        try:
            await AsyncKicker(task_name=task_name, broker=broker, labels={}).schedule_by_time(
                redis_schedule_source, utcnow() + timedelta(seconds=delay_seconds), *args, **kwargs
            )
            return True
        except Exception as e:
            logger.warning('Could not schedule {} {}: {}', task_name, args, e)
            return False
