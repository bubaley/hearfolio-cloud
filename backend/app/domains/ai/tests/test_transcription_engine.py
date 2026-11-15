from pathlib import Path

import httpx2
import pytest

from app.domains.ai.services.audio_segmenter import AudioSegmenter, SegmentRange
from app.domains.ai.services.openrouter_client import AIErrorCode, OpenRouterClient
from app.domains.ai.services.transcription_engine import (
    TranscribedSegment,
    TranscriptionEngine,
    TranscriptionError,
    TranscriptionMode,
    max_tokens_for,
)
from app.domains.ai.tests.fakes import FakeProvider, chat_reply, error_reply, no_sleep
from app.domains.ai.utils.transcript_phrases import Phrase


class FakeSegmenter(AudioSegmenter):
    """Writes placeholder chunk files instead of running ffmpeg; `silent` lists silent start offsets."""

    def __init__(self, silent: set[int] | None = None):
        super().__init__()
        self.cuts: list[tuple[int, int]] = []
        self.silent = silent or set()

    async def cut(self, source: Path, start_ms: int, end_ms: int, target_dir: Path) -> Path:
        self.cuts.append((start_ms, end_ms))
        path = target_dir / f'{start_ms}-{end_ms}.mp3'
        path.write_bytes(f'{start_ms}-{end_ms}'.encode())
        return path

    async def is_silent(self, chunk: Path) -> bool:
        return int(chunk.name.split('-')[0]) in self.silent


class Sink:
    def __init__(self):
        self.calls: list[tuple[TranscribedSegment, int, int]] = []

    async def __call__(self, segment: TranscribedSegment, done: int, total: int) -> None:
        self.calls.append((segment, done, total))


def make_engine(provider: FakeProvider, segmenter: AudioSegmenter, **kwargs) -> TranscriptionEngine:
    client = OpenRouterClient('https://router.test/api/v1', 'key', transport=provider.transport, sleep=no_sleep)
    return TranscriptionEngine(client, segmenter, model='google/gemini', sleep=no_sleep, **kwargs)


PLAN = AudioSegmenter.plan(600_000, 300)


@pytest.mark.asyncio
async def test_segments_are_delivered_in_order_with_offsets(tmp_path):
    provider = FakeProvider().add('/chat/completions', chat_reply('Первый.'), chat_reply('Второй.'))
    sink = Sink()
    results = await make_engine(provider, FakeSegmenter()).transcribe(
        tmp_path / 'audio.m4a', tmp_path, segments=PLAN, on_segment=sink
    )
    assert [r.text for r in results] == ['Первый.', 'Второй.']
    assert [(s.start_ms, s.end_ms, done, total) for s, done, total in sink.calls] == [
        (0, 300_000, 1, 2),
        (300_000, 600_000, 2, 2),
    ]
    body = provider.bodies('/chat/completions')[0]
    assert body['max_tokens'] == max_tokens_for(300_000) >= 12000
    assert 'verbatim' in body['messages'][-1]['content'][0]['text']
    assert list(tmp_path.glob('*.mp3')) == []


@pytest.mark.asyncio
async def test_length_cutoff_retries_only_that_segment(tmp_path):
    provider = FakeProvider().add(
        '/chat/completions',
        chat_reply('Первый.'),
        chat_reply('Второй обрыв', finish_reason='length'),
        chat_reply('Второй целиком.'),
    )
    sink = Sink()
    results = await make_engine(provider, FakeSegmenter()).transcribe(
        tmp_path / 'a.m4a', tmp_path, segments=PLAN, on_segment=sink
    )
    assert [r.text for r in results] == ['Первый.', 'Второй целиком.']
    assert len(provider.calls('/chat/completions')) == 3


@pytest.mark.asyncio
async def test_resume_skips_finished_segments(tmp_path):
    provider = FakeProvider().add('/chat/completions', chat_reply('Второй.'))
    segmenter = FakeSegmenter()
    sink = Sink()
    results = await make_engine(provider, segmenter).transcribe(
        tmp_path / 'a.m4a', tmp_path, segments=PLAN, on_segment=sink, skip={0}
    )
    assert [r.index for r in results] == [1]
    assert segmenter.cuts == [(300_000, 600_000)]
    assert sink.calls[0][1:] == (2, 2)


@pytest.mark.asyncio
async def test_repeated_failure_falls_back_to_halves(tmp_path):
    provider = FakeProvider().add(
        '/chat/completions',
        chat_reply('', finish_reason='stop'),
        chat_reply('обрыв', finish_reason='length'),
        chat_reply(''),
        chat_reply('Первая половина.'),
        chat_reply('Вторая половина.'),
    )
    segmenter = FakeSegmenter()
    segment = SegmentRange(0, 0, 300_000)
    phrases = await make_engine(provider, segmenter).transcribe_range(tmp_path / 'a.m4a', tmp_path, segment)
    # Each half keeps its own time range.
    assert phrases == [Phrase(0, 150_000, 'Первая половина.'), Phrase(150_000, 300_000, 'Вторая половина.')]
    assert segmenter.cuts == [(0, 300_000), (0, 150_000), (150_000, 300_000)]
    assert len(provider.calls('/chat/completions')) == 5


@pytest.mark.asyncio
async def test_final_failure_raises_with_segment_and_russian_message(tmp_path):
    provider = FakeProvider().add('/chat/completions', chat_reply('обрыв', finish_reason='length'))
    with pytest.raises(TranscriptionError) as raised:
        await make_engine(provider, FakeSegmenter()).transcribe_range(
            tmp_path / 'a.m4a', tmp_path, SegmentRange(3, 900_000, 1_200_000)
        )
    assert raised.value.segment.index == 3
    assert raised.value.code == AIErrorCode.INCOMPLETE
    assert raised.value.message == 'Модель вернула только часть текста'
    # 3 attempts on the whole segment + 3 on the first half
    assert len(provider.calls('/chat/completions')) == 6


@pytest.mark.asyncio
async def test_non_retryable_error_stops_immediately(tmp_path):
    provider = FakeProvider().add('/chat/completions', error_reply(401))
    sink = Sink()
    with pytest.raises(TranscriptionError) as raised:
        await make_engine(provider, FakeSegmenter()).transcribe(
            tmp_path / 'a.m4a', tmp_path, segments=PLAN, on_segment=sink
        )
    assert raised.value.code == AIErrorCode.AUTH
    assert len(provider.calls('/chat/completions')) == 1
    assert sink.calls == []


@pytest.mark.asyncio
async def test_silent_chunks_are_not_sent(tmp_path):
    provider = FakeProvider().add('/chat/completions', chat_reply('Речь.'))
    results = await make_engine(provider, FakeSegmenter(silent={0})).transcribe(
        tmp_path / 'a.m4a', tmp_path, segments=PLAN, on_segment=Sink()
    )
    assert [r.text for r in results] == ['', 'Речь.']
    assert len(provider.calls('/chat/completions')) == 1


@pytest.mark.asyncio
async def test_no_speech_marker_and_fences_are_cleaned(tmp_path):
    provider = FakeProvider().add('/chat/completions', chat_reply('NO_SPEECH'), chat_reply('```\nТекст\n```'))
    results = await make_engine(provider, FakeSegmenter()).transcribe(
        tmp_path / 'a.m4a', tmp_path, segments=PLAN, on_segment=Sink()
    )
    assert [r.text for r in results] == ['', 'Текст']


@pytest.mark.asyncio
async def test_transcription_mode_uses_audio_transcriptions_endpoint(tmp_path):
    provider = FakeProvider().add('/audio/transcriptions', httpx2.Response(200, json={'text': 'Привет'}))
    engine = make_engine(provider, FakeSegmenter(), mode=TranscriptionMode.TRANSCRIPTION, language='ru')
    phrases = await engine.transcribe_range(tmp_path / 'a.m4a', tmp_path, SegmentRange(0, 0, 60_000))
    assert phrases == [Phrase(0, 60_000, 'Привет')]
    body = provider.bodies('/audio/transcriptions')[0]
    assert body['input_audio']['format'] == 'mp3'
    assert body['language'] == 'ru'


def stt_reply(*words: tuple[str, float, float, int]) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            'text': ' '.join(word for word, *_ in words),
            'words': [{'word': w, 'start': s, 'end': e, 'speaker': p} for w, s, e, p in words],
        },
    )


@pytest.mark.asyncio
async def test_transcription_mode_builds_timed_phrases_with_scoped_speakers(tmp_path):
    provider = FakeProvider().add(
        '/audio/transcriptions',
        stt_reply(('Привет.', 0.5, 1.0, 0), ('Здравствуй.', 3.0, 4.0, 1)),
        stt_reply(('Пока.', 1.0, 2.0, 0)),
    )
    sink = Sink()
    engine = make_engine(provider, FakeSegmenter(), mode=TranscriptionMode.TRANSCRIPTION)
    results = await engine.transcribe(tmp_path / 'a.m4a', tmp_path, segments=PLAN, on_segment=sink)
    assert results[0].phrases == (
        Phrase(500, 1000, 'Привет.', '0:0'),
        Phrase(3000, 4000, 'Здравствуй.', '0:1'),
    )
    assert results[0].text == 'Привет. Здравствуй.'
    # The second request's speaker 0 is not the first one's.
    assert results[1].phrases == (Phrase(301_000, 302_000, 'Пока.', '300000:0'),)


async def _split_in_two(segment: SegmentRange) -> list[SegmentRange]:
    middle = (segment.start_ms + segment.end_ms) // 2
    return [SegmentRange(0, segment.start_ms, middle), SegmentRange(1, middle, segment.end_ms)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'failure',
    [error_reply(504, 'Upstream timed out'), error_reply(413, 'Payload too large'), error_reply(400, 'large audio')],
)
async def test_long_chunk_falls_back_to_normal_chunks_after_one_attempt(tmp_path, failure):
    provider = FakeProvider().add(
        '/audio/transcriptions', failure, stt_reply(('Раз.', 1.0, 2.0, 0)), stt_reply(('Два.', 1.0, 2.0, 0))
    )
    segmenter = FakeSegmenter()
    client = OpenRouterClient('https://router.test/api/v1', 'key', transport=provider.transport, max_attempts=1)
    engine = TranscriptionEngine(
        client,
        segmenter,
        model='x-ai/grok-stt',
        mode=TranscriptionMode.TRANSCRIPTION,
        sleep=no_sleep,
        fallback_plan=_split_in_two,
    )
    phrases = await engine.transcribe_range(tmp_path / 'a.m4a', tmp_path, SegmentRange(0, 0, 2_000_000))
    assert phrases == [Phrase(1000, 2000, 'Раз.', '0:0'), Phrase(1_001_000, 1_002_000, 'Два.', '1000000:0')]
    assert segmenter.cuts == [(0, 2_000_000), (0, 1_000_000), (1_000_000, 2_000_000)]


@pytest.mark.asyncio
async def test_long_chunk_does_not_fall_back_on_auth_errors(tmp_path):
    provider = FakeProvider().add('/audio/transcriptions', error_reply(401, 'User not found'))
    engine = make_engine(provider, FakeSegmenter(), mode=TranscriptionMode.TRANSCRIPTION, fallback_plan=_split_in_two)
    with pytest.raises(TranscriptionError) as raised:
        await engine.transcribe_range(tmp_path / 'a.m4a', tmp_path, SegmentRange(0, 0, 2_000_000))
    assert raised.value.code == AIErrorCode.AUTH
    assert len(provider.calls('/audio/transcriptions')) == 1
