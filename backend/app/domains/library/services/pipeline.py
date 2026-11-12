"""
Seam between the library and the processing pipeline (`domains/ai`). The library never imports the ai domain:

- after an upload completes, `RecordingPipeline.enqueue` kicks the Taskiq task named `PROCESS_RECORDING_TASK`
  by name; the ai domain registers a task with that name and decides what to run (transcription, title,
  tags, project suggestion, summaries) from its settings;
- the pipeline writes back only through `RecordingService` (progress, transcript, failures, title, tags,
  project suggestion, events), which keeps the journal and realtime events consistent;
- public share links ask `RecordingPipeline.shared_results` for the summaries a link exposes; the ai domain
  plugs a provider in with `RecordingPipeline.register_share_results_provider`.

See docs/pipeline-seam.md.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from loguru import logger
from taskiq.kicker import AsyncKicker

from app.core.broker import broker
from app.core.settings import settings
from app.domains.library.models import Recording

PROCESS_RECORDING_TASK = 'ai.process_recording'

# (recording, result ids allowed by the link) -> JSON-serializable results, in the order to show them
ShareResultsProvider = Callable[[Recording, list[UUID]], Awaitable[list[dict[str, Any]]]]
# (recording, result ids) -> the ids among them that are results of this recording
ResultIdsChecker = Callable[[Recording, list[UUID]], Awaitable[set[UUID]]]


class _RecordingPipeline:
    def __init__(self) -> None:
        self._share_results_provider: ShareResultsProvider | None = None
        self._result_ids_checker: ResultIdsChecker | None = None

    async def enqueue(self, recording: Recording) -> bool:
        """
        Kick `ai.process_recording(recording_id: str)`. Returns False when nothing could be enqueued
        (no such task in a test process, broker unavailable); the recording then stays `queued` and can be retried.
        """
        task = broker.find_task(PROCESS_RECORDING_TASK)
        try:
            if task is not None:
                await task.kiq(str(recording.id))
                return True
            if settings.testing:
                # The in-memory broker can only run tasks registered in this process.
                return False
            # The API process may not import the ai tasks module; the worker resolves the task by name.
            await AsyncKicker(task_name=PROCESS_RECORDING_TASK, broker=broker, labels={}).kiq(str(recording.id))
            return True
        except Exception as e:
            logger.warning('Could not enqueue {} for recording {}: {}', PROCESS_RECORDING_TASK, recording.id, e)
            return False

    def register_share_results_provider(self, provider: ShareResultsProvider | None) -> None:
        self._share_results_provider = provider

    def register_result_ids_checker(self, checker: ResultIdsChecker | None) -> None:
        self._result_ids_checker = checker

    async def known_result_ids(self, recording: Recording, result_ids: list[UUID]) -> set[UUID]:
        """The ids among `result_ids` that belong to the recording; none without the ai domain."""
        if not result_ids or self._result_ids_checker is None:
            return set()
        return await self._result_ids_checker(recording, result_ids)

    async def shared_results(self, recording: Recording, result_ids: list[UUID]) -> list[dict[str, Any]]:
        if not result_ids or self._share_results_provider is None:
            return []
        return await self._share_results_provider(recording, result_ids)


RecordingPipeline = _RecordingPipeline()
