import asyncio
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from loguru import logger

from app.domains.ai.prompts import transcription_prompt
from app.domains.ai.services.audio_segmenter import SEGMENT_FORMAT, AudioSegmenter, SegmentRange
from app.domains.ai.services.openrouter_client import AIErrorCode, AIProviderError, ChatResult, OpenRouterClient
from app.domains.ai.utils.model_output import clean_transcript

# Speech rarely exceeds ~200 words/min; Russian costs ~3 tokens a word. Reasoning models spend part of the budget
# before answering, so the limit is generous: an early cut-off (`finish_reason=length`) is what loses text.
TOKENS_PER_AUDIO_SECOND = 40
MIN_MAX_TOKENS = 4096
MAX_MAX_TOKENS = 32000
# Sub-chunks of a failed segment are not split again below this length.
MIN_SPLIT_MS = 20_000


class TranscriptionMode(StrEnum):
    # `chat/completions` with an `input_audio` part (Gemini, GPT-4o audio, …)
    CHAT = 'chat'
    # `/audio/transcriptions` for dedicated speech-to-text models
    TRANSCRIPTION = 'transcription'


@dataclass(frozen=True)
class TranscribedSegment:
    index: int
    start_ms: int
    end_ms: int
    text: str


# Receives each finished segment with (done, total) right away, so a crash after it loses nothing.
SegmentSink = Callable[[TranscribedSegment, int, int], Awaitable[None]]


class TranscriptionError(Exception):
    """A segment could not be transcribed; `message` is Russian, `code` an `AIErrorCode`/`audio` value."""

    def __init__(self, segment: SegmentRange, code: str, message: str):
        self.segment = segment
        self.code = code
        self.message = message
        super().__init__(message)


def max_tokens_for(duration_ms: int) -> int:
    return min(max(duration_ms // 1000 * TOKENS_PER_AUDIO_SECOND, MIN_MAX_TOKENS), MAX_MAX_TOKENS)


def timeout_for(duration_ms: int) -> float:
    return max(120.0, duration_ms / 1000 * 1.5)


class TranscriptionEngine:
    """
    Transcribes an audio file segment by segment. Each segment is retried on its own (`finish_reason=length`, empty
    text, transient provider errors) with exponential backoff; after the last attempt it is split in half once and
    each half transcribed separately. Segments listed in `skip` (already saved) are not sent again.
    """

    def __init__(
        self,
        client: OpenRouterClient,
        segmenter: AudioSegmenter,
        *,
        model: str,
        language: str | None = 'auto',
        mode: TranscriptionMode = TranscriptionMode.CHAT,
        attempts: int = 3,
        backoff_seconds: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.client = client
        self.segmenter = segmenter
        self.model = model
        self.language = language
        self.mode = mode
        self.attempts = max(1, attempts)
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep

    async def transcribe(
        self,
        source: Path,
        work_dir: Path,
        *,
        segments: list[SegmentRange],
        on_segment: SegmentSink,
        skip: Collection[int] = (),
    ) -> list[TranscribedSegment]:
        """Transcribe `segments` of `source` in order; returns only the newly transcribed ones."""
        total = len(segments)
        done = sum(1 for segment in segments if segment.index in skip)
        results: list[TranscribedSegment] = []
        for segment in segments:
            if segment.index in skip:
                continue
            text = await self.transcribe_range(source, work_dir, segment)
            result = TranscribedSegment(segment.index, segment.start_ms, segment.end_ms, text)
            done += 1
            await on_segment(result, done, total)
            results.append(result)
        return results

    async def transcribe_range(self, source: Path, work_dir: Path, segment: SegmentRange) -> str:
        chunk = await self.segmenter.cut(source, segment.start_ms, segment.end_ms, work_dir)
        try:
            if await self.segmenter.is_silent(chunk):
                return ''
            try:
                return await self._with_retries(chunk, segment)
            except AIProviderError as error:
                if not error.retryable or segment.duration_ms < MIN_SPLIT_MS * 2:
                    raise TranscriptionError(segment, error.code, error.message) from error
                logger.warning('Segment {} failed ({}), retrying as two halves', segment.index, error.code)
            middle = segment.start_ms + segment.duration_ms // 2
            parts = []
            for start, end in ((segment.start_ms, middle), (middle, segment.end_ms)):
                half = SegmentRange(segment.index, start, end)
                half_chunk = await self.segmenter.cut(source, start, end, work_dir)
                try:
                    if await self.segmenter.is_silent(half_chunk):
                        continue
                    parts.append(await self._with_retries(half_chunk, half))
                except AIProviderError as error:
                    raise TranscriptionError(segment, error.code, error.message) from error
                finally:
                    half_chunk.unlink(missing_ok=True)
            return ' '.join(part for part in parts if part)
        finally:
            chunk.unlink(missing_ok=True)

    async def _with_retries(self, chunk: Path, segment: SegmentRange) -> str:
        audio = chunk.read_bytes()
        for attempt in range(1, self.attempts + 1):
            try:
                return await self._request(audio, segment)
            except AIProviderError as error:
                if not error.retryable or attempt >= self.attempts:
                    raise
                delay = min(self.backoff_seconds * (2 ** (attempt - 1)), 60.0)
                if error.retry_after is not None:
                    delay = max(delay, min(error.retry_after, 60.0))
                logger.warning(
                    'Segment {} [{}-{} ms] attempt {}/{} failed ({}): {}',
                    segment.index,
                    segment.start_ms,
                    segment.end_ms,
                    attempt,
                    self.attempts,
                    error.code,
                    error.detail,
                )
                await self._sleep(delay)
        raise AssertionError('unreachable')

    async def _request(self, audio: bytes, segment: SegmentRange) -> str:
        if self.mode == TranscriptionMode.TRANSCRIPTION:
            language = None if not self.language or self.language == 'auto' else self.language
            result = await self.client.transcribe(
                model=self.model,
                audio=audio,
                audio_format=SEGMENT_FORMAT,
                language=language,
                timeout=timeout_for(segment.duration_ms),
            )
        else:
            result = await self.client.chat_audio(
                model=self.model,
                prompt=transcription_prompt(self.language),
                audio=audio,
                audio_format=SEGMENT_FORMAT,
                max_tokens=max_tokens_for(segment.duration_ms),
                timeout=timeout_for(segment.duration_ms),
            )
        return self._accept(result)

    @staticmethod
    def _accept(result: ChatResult) -> str:
        if result.finish_reason == 'length':
            raise AIProviderError(AIErrorCode.INCOMPLETE, detail='finish_reason=length')
        if not result.text.strip():
            raise AIProviderError(AIErrorCode.EMPTY, detail=f'finish_reason={result.finish_reason}')
        return clean_transcript(result.text)
