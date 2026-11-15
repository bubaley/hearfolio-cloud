import asyncio
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from loguru import logger

from app.domains.ai.prompts import transcription_prompt
from app.domains.ai.services.audio_segmenter import SEGMENT_FORMAT, AudioSegmenter, SegmentRange
from app.domains.ai.services.openrouter_client import (
    AIErrorCode,
    AIProviderError,
    ChatResult,
    OpenRouterClient,
    TranscriptionResult,
)
from app.domains.ai.utils.model_output import clean_transcript
from app.domains.ai.utils.transcript_phrases import Phrase, build_phrases

# Speech rarely exceeds ~200 words/min; Russian costs ~3 tokens a word. Reasoning models spend part of the budget
# before answering, so the limit is generous: an early cut-off (`finish_reason=length`) is what loses text.
TOKENS_PER_AUDIO_SECOND = 40
MIN_MAX_TOKENS = 4096
MAX_MAX_TOKENS = 32000
# Sub-chunks of a failed segment are not split again below this length.
MIN_SPLIT_MS = 20_000
# Speech-to-text endpoints answer far faster than real time (Grok: 44 min of audio in ~23 s), so their wait is capped.
TRANSCRIPTION_MAX_TIMEOUT = 300.0
# Speech-to-text models that tell speakers apart get long chunks: speaker ids hold only within one request, so a
# typical meeting should be one request. Measured on Grok STT (mono 16 kHz mp3 32 kbit/s, diarization on): 10 min in
# 4 s, 20 min in 7 s, 30 min in 15 s, 44 min in 23 s (14 MB of base64). 45 min keeps >2x margin to OpenRouter's 60 s
# upstream timeout and ~1.7x to the 25 MB body limit. Deepgram refuses inputs of 20 min («large audio»), so it is
# not listed.
LONG_CHUNK_SECONDS = 2700
LONG_CHUNK_MODEL_PREFIXES = ('x-ai/',)


class TranscriptionMode(StrEnum):
    # `chat/completions` with an `input_audio` part (Gemini, GPT-4o audio, …)
    CHAT = 'chat'
    # `/audio/transcriptions` for dedicated speech-to-text models
    TRANSCRIPTION = 'transcription'


@dataclass(frozen=True)
class TranscribedSegment:
    """One finished chunk. `phrases` (absolute times, in order) is empty only for a silent chunk."""

    index: int
    start_ms: int
    end_ms: int
    text: str
    phrases: tuple[Phrase, ...] = ()


# Receives each finished segment with (done, total) right away, so a crash after it loses nothing.
SegmentSink = Callable[[TranscribedSegment, int, int], Awaitable[None]]
# A chunk too long or too slow for one request -> the normal-size chunks to transcribe it as instead.
FallbackPlan = Callable[[SegmentRange], Awaitable[list[SegmentRange]]]


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


def long_chunk_seconds(model: str, mode: TranscriptionMode) -> int | None:
    """The chunk length for a diarizing speech-to-text model, `None` for every other model (normal chunks)."""
    if mode == TranscriptionMode.TRANSCRIPTION and model.startswith(LONG_CHUNK_MODEL_PREFIXES):
        return LONG_CHUNK_SECONDS
    return None


class TranscriptionEngine:
    """
    Transcribes an audio file segment by segment. Each segment is retried on its own (`finish_reason=length`, empty
    text, transient provider errors) with exponential backoff; after the last attempt it is split in half once and
    each half transcribed separately. Segments listed in `skip` (already saved) are not sent again; indices only
    identify ranges within one plan, so `skip` must come from the same `segments` list.

    Each request becomes timed phrases (`build_phrases`): word/segment timestamps and speakers when the model returns
    them, one phrase for the request otherwise. With `fallback_plan` (long chunks for diarizing models) a chunk gets
    one attempt; a timeout, size or transient failure re-cuts it into normal chunks instead of retrying it whole.
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
        fallback_plan: FallbackPlan | None = None,
    ):
        self.client = client
        self.segmenter = segmenter
        self.model = model
        self.language = language
        self.mode = mode
        self.attempts = max(1, attempts)
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self.fallback_plan = fallback_plan

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
            phrases = await self.transcribe_range(source, work_dir, segment)
            text = ' '.join(phrase.text for phrase in phrases)
            result = TranscribedSegment(segment.index, segment.start_ms, segment.end_ms, text, tuple(phrases))
            done += 1
            await on_segment(result, done, total)
            results.append(result)
        return results

    async def transcribe_range(self, source: Path, work_dir: Path, segment: SegmentRange) -> list[Phrase]:
        """Phrases of one chunk (empty when it is silent)."""
        if self.fallback_plan is None:
            return await self._transcribe_range(source, work_dir, segment)
        chunk = await self.segmenter.cut(source, segment.start_ms, segment.end_ms, work_dir)
        try:
            if await self.segmenter.is_silent(chunk):
                return []
            return await self._request(chunk.read_bytes(), segment)
        except AIProviderError as error:
            if not error.retryable and error.code != AIErrorCode.TOO_LARGE:
                raise TranscriptionError(segment, error.code, error.message) from error
            parts = await self.fallback_plan(segment)
            logger.warning(
                'Long segment {} [{}-{} ms] failed ({}): {}; transcribing it as {} chunks',
                segment.index,
                segment.start_ms,
                segment.end_ms,
                error.code,
                error.detail,
                len(parts),
            )
        finally:
            chunk.unlink(missing_ok=True)
        phrases: list[Phrase] = []
        for part in parts:
            phrases += await self._transcribe_range(
                source, work_dir, SegmentRange(segment.index, part.start_ms, part.end_ms)
            )
        return phrases

    async def _transcribe_range(self, source: Path, work_dir: Path, segment: SegmentRange) -> list[Phrase]:
        chunk = await self.segmenter.cut(source, segment.start_ms, segment.end_ms, work_dir)
        try:
            if await self.segmenter.is_silent(chunk):
                return []
            try:
                return await self._with_retries(chunk, segment)
            except AIProviderError as error:
                if not error.retryable or segment.duration_ms < MIN_SPLIT_MS * 2:
                    raise TranscriptionError(segment, error.code, error.message) from error
                logger.warning('Segment {} failed ({}), retrying as two halves', segment.index, error.code)
            middle = segment.start_ms + segment.duration_ms // 2
            phrases: list[Phrase] = []
            for start, end in ((segment.start_ms, middle), (middle, segment.end_ms)):
                half = SegmentRange(segment.index, start, end)
                half_chunk = await self.segmenter.cut(source, start, end, work_dir)
                try:
                    if await self.segmenter.is_silent(half_chunk):
                        continue
                    phrases += await self._with_retries(half_chunk, half)
                except AIProviderError as error:
                    raise TranscriptionError(segment, error.code, error.message) from error
                finally:
                    half_chunk.unlink(missing_ok=True)
            return phrases
        finally:
            chunk.unlink(missing_ok=True)

    async def _with_retries(self, chunk: Path, segment: SegmentRange) -> list[Phrase]:
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

    async def _request(self, audio: bytes, segment: SegmentRange) -> list[Phrase]:
        """Phrases of one request (none when the model reports no speech); EMPTY / INCOMPLETE answers raise."""
        if self.mode == TranscriptionMode.TRANSCRIPTION:
            language = None if not self.language or self.language == 'auto' else self.language
            result: ChatResult = await self.client.transcribe(
                model=self.model,
                audio=audio,
                audio_format=SEGMENT_FORMAT,
                language=language,
                timeout=min(timeout_for(segment.duration_ms), TRANSCRIPTION_MAX_TIMEOUT),
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
        text = self._accept(result)
        if not text:
            # The model reported no speech.
            return []
        if isinstance(result, TranscriptionResult):
            phrases = build_phrases(
                offset_ms=segment.start_ms,
                duration_ms=segment.duration_ms,
                text=text,
                words=result.words,
                segments=result.segments,
            )
            if phrases:
                return phrases
        return [Phrase(segment.start_ms, segment.end_ms, text)]

    @staticmethod
    def _accept(result: ChatResult) -> str:
        if result.finish_reason == 'length':
            raise AIProviderError(AIErrorCode.INCOMPLETE, detail='finish_reason=length')
        if not result.text.strip():
            raise AIProviderError(AIErrorCode.EMPTY, detail=f'finish_reason={result.finish_reason}')
        return clean_transcript(result.text)
