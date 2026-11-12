import time
import uuid
from typing import ClassVar

from loguru import logger

from app.core.redis import get_redis
from app.core.settings import settings

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end
"""
_EXTEND_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end
"""
# A pending request survives at most this long without a holder picking it up (a crashed worker's lock expires
# sooner, so the next kick or the stale sweeper handles it).
PENDING_TTL_SECONDS = 60 * 60


class LockUnavailableError(RuntimeError):
    """Redis could not be asked: the caller must not run (fail closed) and should try again later."""


class ProcessingLock:
    """
    One pipeline run per recording at a time (a double «Повторить», a re-delivered message). Redis `SET NX` with a
    TTL that the holder extends after every segment, so a crashed worker's lock expires on its own.

    A request that finds the lock busy is not lost: it leaves a *pending* marker (`mark_pending`) and the holder
    picks it up after releasing (`take_pending`), see `RecordingProcessor.process`. Redis errors raise
    `LockUnavailableError` (fail closed); only tests use process memory.
    """

    _memory: ClassVar[dict[str, tuple[str, float]]] = {}
    _memory_pending: ClassVar[dict[str, bool]] = {}

    def __init__(self, name: str, ttl_seconds: int = 15 * 60):
        self.key = f'ai:lock:{name}'
        self.pending_key = f'ai:pending:{name}'
        self.ttl_seconds = ttl_seconds
        self.token = uuid.uuid4().hex

    @staticmethod
    def _use_redis() -> bool:
        return not settings.testing

    async def acquire(self) -> bool:
        if self._use_redis():
            try:
                return bool(await get_redis().set(self.key, self.token, nx=True, ex=self.ttl_seconds))
            except Exception as e:
                raise LockUnavailableError(str(e)) from e
        holder = self._memory.get(self.key)
        if holder and holder[1] > time.monotonic():
            return False
        self._memory[self.key] = (self.token, time.monotonic() + self.ttl_seconds)
        return True

    async def extend(self) -> None:
        if self._use_redis():
            try:
                await get_redis().eval(_EXTEND_SCRIPT, 1, self.key, self.token, self.ttl_seconds)
            except Exception as e:
                # The run goes on; the lock may expire early, the next acquire still sees Redis state.
                logger.warning('Processing lock extend failed: {}', e)
            return
        if (holder := self._memory.get(self.key)) and holder[0] == self.token:
            self._memory[self.key] = (self.token, time.monotonic() + self.ttl_seconds)

    async def release(self) -> None:
        if self._use_redis():
            # A failed release leaves the lock to expire by its TTL.
            await get_redis().eval(_RELEASE_SCRIPT, 1, self.key, self.token)
            return
        if (holder := self._memory.get(self.key)) and holder[0] == self.token:
            del self._memory[self.key]

    async def mark_pending(self, force: bool) -> None:
        """Ask the current holder to run once more after it finishes (`force` wins over a non-forced request)."""
        if self._use_redis():
            try:
                redis = get_redis()
                if force:
                    await redis.set(self.pending_key, '1', ex=PENDING_TTL_SECONDS)
                else:
                    await redis.set(self.pending_key, '0', nx=True, ex=PENDING_TTL_SECONDS)
            except Exception as e:
                raise LockUnavailableError(str(e)) from e
            return
        self._memory_pending[self.pending_key] = self._memory_pending.get(self.pending_key, False) or force

    async def take_pending(self) -> bool | None:
        """Consume the pending marker: None when there is none, otherwise its `force` flag."""
        if self._use_redis():
            try:
                value = await get_redis().getdel(self.pending_key)
            except Exception as e:
                raise LockUnavailableError(str(e)) from e
            if value is None:
                return None
            return (value.decode() if isinstance(value, bytes) else str(value)) == '1'
        return self._memory_pending.pop(self.pending_key, None)
