from typing import Any

from loguru import logger
from taskiq.kicker import AsyncKicker

from app.core.broker import broker
from app.core.settings import settings
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
