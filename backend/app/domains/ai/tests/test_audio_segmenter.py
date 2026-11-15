import asyncio
import itertools
import shutil
from pathlib import Path

import pytest

from app.domains.ai.services.audio_segmenter import (
    MAX_PAUSES,
    AudioProcessingError,
    AudioSegmenter,
    Pause,
    SegmentRange,
    parse_pauses,
    pick_boundary,
    search_window_ms,
)

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


def _bounds(plan: list[SegmentRange]) -> list[tuple[int, int]]:
    return [(segment.start_ms, segment.end_ms) for segment in plan]


def _assert_contiguous(plan: list[SegmentRange], start_ms: int, duration_ms: int) -> None:
    assert [segment.index for segment in plan] == list(range(len(plan)))
    assert plan[0].start_ms == start_ms and plan[-1].end_ms == duration_ms
    assert all(left.end_ms == right.start_ms for left, right in itertools.pairwise(plan))
    assert all(segment.duration_ms > 0 for segment in plan)


def test_search_window_is_capped_by_a_share_of_the_chunk():
    assert search_window_ms(300) == 30_000
    assert search_window_ms(60) == 12_000


def test_plan_cuts_in_the_middle_of_a_pause_inside_the_window():
    plan = AudioSegmenter.plan(650_000, 300, [Pause(290_000, 291_000), Pause(605_000, 607_000)])
    assert _bounds(plan) == [(0, 290_500), (290_500, 606_000), (606_000, 650_000)]
    _assert_contiguous(plan, 0, 650_000)


def test_plan_ignores_pauses_outside_the_window():
    # 300 s chunks search ±30 s: a pause at 250 s or 340 s is too far, the target is used.
    plan = AudioSegmenter.plan(650_000, 300, [Pause(250_000, 255_000), Pause(340_000, 345_000)])
    assert _bounds(plan) == [(0, 300_000), (300_000, 600_000), (600_000, 650_000)]


def test_plan_prefers_longer_pauses_and_then_closer_ones():
    # A 2.5 s pause 15 s away beats a 0.5 s one at the target.
    assert AudioSegmenter.plan(650_000, 300, [Pause(299_750, 300_250), Pause(314_000, 316_500)])[0].end_ms == 315_250
    # Equally long pauses: the closer one wins.
    assert AudioSegmenter.plan(650_000, 300, [Pause(280_000, 281_000), Pause(304_000, 305_000)])[0].end_ms == 304_500
    # Past PAUSE_SCORE_CAP_MS length stops mattering: a 3 s pause near the target beats a 10 s one far away.
    assert AudioSegmenter.plan(650_000, 300, [Pause(301_000, 304_000), Pause(320_000, 330_000)])[0].end_ms == 302_500


def test_pick_boundary_clips_a_long_pause_to_the_window_and_breaks_ties_early():
    # A pause covering the window edge is cut in the middle of its part inside the window.
    assert pick_boundary(300_000, 270_000, 330_000, [Pause(320_000, 400_000)]) == 325_000
    assert pick_boundary(300_000, 270_000, 330_000, [Pause(290_000, 291_000), Pause(309_000, 310_000)]) == 290_500
    assert pick_boundary(300_000, 270_000, 330_000, []) == 300_000


def test_plan_measures_each_chunk_from_the_previous_cut():
    plan = AudioSegmenter.plan(700_000, 300, [Pause(280_000, 282_000)])
    # The second target is 281 s + 300 s, not 600 s.
    assert _bounds(plan) == [(0, 281_000), (281_000, 581_000), (581_000, 700_000)]


def test_plan_keeps_the_tail_rule_with_pauses():
    # A pause that would leave a tail under 15 s is out of reach; the tail merges as before.
    assert _bounds(AudioSegmenter.plan(310_000, 300, [Pause(299_000, 300_000)])) == [(0, 310_000)]
    # A pause reaching into the forbidden tail is used only up to the last allowed cut.
    plan = AudioSegmenter.plan(330_000, 300, [Pause(312_000, 325_000)])
    assert _bounds(plan) == [(0, 313_500), (313_500, 330_000)]
    assert AudioSegmenter.plan(4_000, 300, [Pause(1_000, 2_000)]) == [SegmentRange(0, 0, 4_000)]
    assert AudioSegmenter.plan(0, 300, [Pause(0, 1_000)]) == []


def test_plan_resumes_from_an_offset_and_is_deterministic():
    pauses = [Pause(400_000, 401_000), Pause(710_000, 712_000), Pause(1_010_000, 1_011_000)]
    plan = AudioSegmenter.plan(1_200_000, 300, pauses, start_ms=120_000)
    assert _bounds(plan) == [(120_000, 400_500), (400_500, 711_000), (711_000, 1_010_500), (1_010_500, 1_200_000)]
    _assert_contiguous(plan, 120_000, 1_200_000)
    assert AudioSegmenter.plan(1_200_000, 300, list(reversed(pauses)), start_ms=120_000) == plan
    assert AudioSegmenter.plan(1_200_000, 300, start_ms=1_200_000) == []


def test_plan_covers_long_audio_with_dense_pauses():
    duration = 3 * 3600 * 1000
    pauses = [Pause(ms, ms + 600) for ms in range(7_000, duration, 7_000)]
    plan = AudioSegmenter.plan(duration, 300, pauses)
    _assert_contiguous(plan, 0, duration)
    window = search_window_ms(300)
    assert all(300_000 - window <= segment.duration_ms <= 300_000 + window for segment in plan[:-1])
    assert all(any(p.start_ms <= segment.end_ms <= p.end_ms for p in pauses) for segment in plan[:-1])


def test_needs_split_matches_the_plan():
    assert not AudioSegmenter.needs_split(314_999, 300)
    assert AudioSegmenter.needs_split(315_000, 300)
    assert len(AudioSegmenter.plan(314_999, 300)) == 1
    assert len(AudioSegmenter.plan(315_000, 300)) == 2


def test_parse_pauses_reads_silencedetect_output():
    log = [
        "Input #0, wav, from 'source':\n",
        '[silencedetect @ 0x6000] silence_start: 0\n',
        '[silencedetect @ 0x6000] silence_end: 1.25 | silence_duration: 1.25\n',
        'size=N/A time=00:00:10.00 bitrate=N/A speed= 500x\n',
        '[silencedetect @ 0x6000] silence_start: 55.0213\n',
        '[silencedetect @ 0x6000] silence_end: 57.004 | silence_duration: 1.98271\n',
        '[silencedetect @ 0x6000] silence_end: 58 | silence_duration: 1\n',  # end without a start: ignored
        '[silencedetect @ 0x6000] silence_start: -0.02\n',
        '[silencedetect @ 0x6000] silence_end: 0.5 | silence_duration: 0.52\n',
        '[silencedetect @ 0x6000] silence_start: 70\n',
        '[silencedetect @ 0x6000] silence_end: 69 | silence_duration: -1\n',  # inverted: dropped
        '[silencedetect @ 0x6000] silence_start: 98.5\n',
    ]
    assert parse_pauses(log, 100_000) == [
        Pause(0, 1_250),
        Pause(55_021, 57_004),
        Pause(0, 500),
        Pause(98_500, 100_000),
    ]
    assert parse_pauses(['silence_start: 120\n'], 100_000) == []
    assert parse_pauses(['silence_start: 90\n', 'silence_end: 130\n'], 100_000) == [Pause(90_000, 100_000)]


def test_parse_pauses_is_bounded():
    log = [line for i in range(10) for line in (f'silence_start: {i}\n', f'silence_end: {i}.5\n')]
    assert len(parse_pauses(log, 100_000, limit=3)) == 3
    assert len(parse_pauses(log, 100_000)) == 10 <= MAX_PAUSES


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


@needs_ffmpeg
@pytest.mark.asyncio
async def test_detect_pauses_and_plan_on_a_real_file(tmp_path):
    """Tone with gaps of silence at 30-31 s (too early for a 60 s chunk) and 56-58 s: the cut lands at ~57 s."""
    source = tmp_path / 'speech.wav'
    expression = 'if(between(t,30,31)+between(t,56,58),0,0.5*sin(2*PI*440*t))'
    await _generate(source, f"aevalsrc='{expression}':s=44100:d=100", 100)
    segmenter = AudioSegmenter()
    duration = await segmenter.probe_duration_ms(source)
    pauses = await segmenter.detect_pauses(source, duration)
    assert len(pauses) == 2
    expected = [(30_000, 31_000), (56_000, 58_000)]
    for pause, (start, end) in zip(pauses, expected):
        assert abs(pause.start_ms - start) < 100 and abs(pause.end_ms - end) < 100
    plan = AudioSegmenter.plan(duration, 60, pauses)
    assert len(plan) == 2
    assert abs(plan[0].end_ms - 57_000) < 100
    assert plan[1].end_ms == duration


@needs_ffmpeg
@pytest.mark.asyncio
async def test_detect_pauses_failure_falls_back_to_no_pauses(tmp_path):
    broken = tmp_path / 'broken.m4a'
    broken.write_bytes(b'not audio')
    assert await AudioSegmenter().detect_pauses(broken, 60_000) == []
    assert await AudioSegmenter(ffmpeg='/nonexistent/ffmpeg').detect_pauses(broken, 60_000) == []
