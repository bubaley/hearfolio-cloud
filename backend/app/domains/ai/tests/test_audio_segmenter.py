import asyncio
import shutil
from pathlib import Path

import pytest

from app.domains.ai.services.audio_segmenter import AudioProcessingError, AudioSegmenter, SegmentRange

needs_ffmpeg = pytest.mark.skipif(not AudioSegmenter.is_available(), reason='ffmpeg/ffprobe not installed')


def test_plan_covers_duration_without_gaps():
    plan = AudioSegmenter.plan(650_000, 300)
    assert plan == [SegmentRange(0, 0, 300_000), SegmentRange(1, 300_000, 600_000), SegmentRange(2, 600_000, 650_000)]
    assert AudioSegmenter.plan(650_000, 300) == plan


def test_plan_merges_a_tiny_tail_and_handles_short_audio():
    assert AudioSegmenter.plan(605_000, 300) == [SegmentRange(0, 0, 300_000), SegmentRange(1, 300_000, 605_000)]
    assert AudioSegmenter.plan(620_000, 300)[-1] == SegmentRange(2, 600_000, 620_000)
    assert AudioSegmenter.plan(4_000, 300) == [SegmentRange(0, 0, 4_000)]
    assert AudioSegmenter.plan(0, 300) == []


async def _generate(path: Path, source: str, seconds: int) -> None:
    process = await asyncio.create_subprocess_exec(
        shutil.which('ffmpeg') or 'ffmpeg',
        '-nostdin',
        '-v',
        'error',
        '-f',
        'lavfi',
        '-i',
        f'{source}:d={seconds}' if source.startswith('sine') else source,
        '-t',
        str(seconds),
        '-ac',
        '2',
        '-ar',
        '44100',
        str(path),
    )
    assert await process.wait() == 0


@needs_ffmpeg
@pytest.mark.asyncio
async def test_probe_cut_and_silence_on_a_real_file():
    segmenter = AudioSegmenter()
    with AudioSegmenter.workspace() as work_dir:
        tone = work_dir / 'tone.wav'
        await _generate(tone, 'sine=frequency=440', 80)
        duration = await segmenter.probe_duration_ms(tone)
        assert abs(duration - 80_000) < 200

        plan = AudioSegmenter.plan(duration, 60)
        assert [(s.start_ms, s.end_ms) for s in plan] == [(0, 60_000), (60_000, duration)]
        chunk = await segmenter.cut(tone, plan[1].start_ms, plan[1].end_ms, work_dir)
        assert chunk.suffix == '.mp3'
        assert abs(await segmenter.probe_duration_ms(chunk) - (duration - 60_000)) < 300
        assert not await segmenter.is_silent(chunk)

        silence = work_dir / 'silence.wav'
        await _generate(silence, 'anullsrc=r=44100:cl=stereo', 5)
        silent_chunk = await segmenter.cut(silence, 0, 5_000, work_dir)
        assert await segmenter.is_silent(silent_chunk)
    assert not work_dir.exists()


@needs_ffmpeg
@pytest.mark.asyncio
async def test_unreadable_file_raises_russian_error(tmp_path):
    broken = tmp_path / 'broken.m4a'
    broken.write_bytes(b'not audio')
    with pytest.raises(AudioProcessingError) as raised:
        await AudioSegmenter().probe_duration_ms(broken)
    assert raised.value.message == 'Не удалось прочитать аудиофайл'


@needs_ffmpeg
@pytest.mark.asyncio
async def test_playlists_referencing_other_files_are_refused(tmp_path):
    """An uploaded HLS/concat playlist must not make ffmpeg read other local files (or the network)."""
    real = tmp_path / 'real.wav'
    await _generate(real, 'sine=frequency=440', 3)
    playlist = tmp_path / 'source'
    playlist.write_text(f'#EXTM3U\n#EXTINF:3,\nfile://{real}\n#EXT-X-ENDLIST\n')
    with pytest.raises(AudioProcessingError):
        await AudioSegmenter().probe_duration_ms(playlist)
    concat = tmp_path / 'concat'
    concat.write_text(f"ffconcat version 1.0\nfile '{real}'\n")
    with pytest.raises(AudioProcessingError):
        await AudioSegmenter().probe_duration_ms(concat)
    # Ordinary audio still works.
    assert abs(await AudioSegmenter().probe_duration_ms(real) - 3000) < 100


@pytest.mark.asyncio
async def test_missing_ffmpeg_is_reported(tmp_path):
    with pytest.raises(AudioProcessingError) as raised:
        await AudioSegmenter(ffprobe='/nonexistent/ffprobe').probe_duration_ms(tmp_path / 'a.mp3')
    assert raised.value.message == 'На сервере не установлен ffmpeg'
