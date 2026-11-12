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


class ProcessingLock:
    """
    One pipeline run per recording at a time (a double «Повторить», a re-delivered message). Redis `SET NX` with a
    TTL that the holder extends after every segment, so a crashed worker's lock expires on its own; process memory
    in tests and while Redis is down.
    """

    _memory: ClassVar[dict[str, tuple[str, float]]] = {}

    def __init__(self, name: str, ttl_seconds: int = 15 * 60):
        self.key = f'ai:lock:{name}'
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
                logger.warning('Processing lock falls back to memory: {}', e)
        holder = self._memory.get(self.key)
        if holder and holder[1] > time.monotonic():
            return False
        self._memory[self.key] = (self.token, time.monotonic() + self.ttl_seconds)
        return True

    async def extend(self) -> None:
        if self._use_redis():
            try:
                await get_redis().eval(_EXTEND_SCRIPT, 1, self.key, self.token, self.ttl_seconds)
                return
            except Exception as e:
                logger.warning('Processing lock extend failed: {}', e)
        if (holder := self._memory.get(self.key)) and holder[0] == self.token:
            self._memory[self.key] = (self.token, time.monotonic() + self.ttl_seconds)

    async def release(self) -> None:
        if self._use_redis():
            try:
                await get_redis().eval(_RELEASE_SCRIPT, 1, self.key, self.token)
            except Exception as e:
                logger.warning('Processing lock release failed: {}', e)
        if (holder := self._memory.get(self.key)) and holder[0] == self.token:
            del self._memory[self.key]
