import asyncio
import json
import re
import shutil
import tempfile
from collections.abc import Generator, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.core.settings import settings

# mp3 is accepted by every OpenRouter audio-input model (`input_audio.format`); mono 16 kHz at 32 kbit/s keeps a
# 5-minute chunk around 1.2 MB (1.6 MB as base64), far below provider request limits.
SEGMENT_FORMAT = 'mp3'
SEGMENT_SAMPLE_RATE = 16000
SEGMENT_BITRATE = '32k'
# A tail shorter than this is merged into the previous segment instead of being sent on its own.
MIN_TAIL_MS = 15_000
# Peak level below which a chunk is treated as silence and not sent to the model.
SILENCE_MAX_VOLUME_DB = -50.0

# Pause detection for chunk boundaries (ffmpeg `silencedetect`). -35 dBFS sits between room noise of a typical voice
# recording (-50…-60) and quiet speech (-20…-30); 0.4 s is longer than the gaps inside words and between most words
# (plosives, short stops are < 0.25 s) but shorter than a normal breath or sentence pause.
PAUSE_NOISE_DB = -35
PAUSE_MIN_SECONDS = 0.4
# A boundary moves at most this far from its target (and never more than a fifth of the chunk length).
PAUSE_SEARCH_WINDOW_MS = 30_000
PAUSE_SEARCH_WINDOW_SHARE = 5
# Pauses longer than this all count as equally safe; beyond it only the distance to the target matters.
PAUSE_SCORE_CAP_MS = 3_000
# Score lost per ms of distance from the target: a pause 20 s away must be ~1 s longer than one at the target.
PAUSE_DISTANCE_WEIGHT = 0.05
# Bound on parsed pauses (a 10-hour file of 0.4 s pauses every second stays far below it).
MAX_PAUSES = 100_000

# Inputs are uploaded files: read local files only (no network, no pipes), only through plain audio/video
# demuxers (no playlists such as HLS or concat that reference other files), and bound how much is probed.
INPUT_FORMATS = 'mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,mp3,ogg,wav,flac,aac,amr,caf,aiff,w64,asf,avi'
SAFE_INPUT_OPTIONS = (
    '-protocol_whitelist',
    'file',
    '-format_whitelist',
    INPUT_FORMATS,
    '-probesize',
    '50000000',
    '-analyzeduration',
    '100000000',
)

_MAX_VOLUME_RE = re.compile(r'max_volume:\s*(-?[\d.]+|-inf)\s*dB')
_SILENCE_START_RE = re.compile(r'silence_start:\s*(-?[\d.]+)')
_SILENCE_END_RE = re.compile(r'silence_end:\s*(-?[\d.]+)')


class AudioProcessingError(Exception):
    """ffmpeg/ffprobe failed; `message` is Russian and safe to show users."""

    def __init__(self, message: str, detail: str = ''):
        self.message = message
        self.detail = detail
        super().__init__(message)


@dataclass(frozen=True)
class SegmentRange:
    index: int
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class Pause:
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def parse_pauses(lines: Iterable[str], duration_ms: int, limit: int = MAX_PAUSES) -> list[Pause]:
    """
    Pauses from `silencedetect` log lines (`silence_start: 12.3`, then `silence_end: 13.1 | …`). A trailing start
    without an end lasts to `duration_ms`; malformed, inverted or out-of-range entries are dropped.
    """
    pauses: list[Pause] = []
    start: float | None = None
    for line in lines:
        if len(pauses) >= limit:
            break
        if (match := _SILENCE_START_RE.search(line)) is not None:
            start = float(match.group(1))
        elif (match := _SILENCE_END_RE.search(line)) is not None and start is not None:
            begin, end = max(round(start * 1000), 0), min(round(float(match.group(1)) * 1000), duration_ms)
            start = None
            if end > begin:
                pauses.append(Pause(begin, end))
    if start is not None and len(pauses) < limit:
        begin = max(round(start * 1000), 0)
        if duration_ms > begin:
            pauses.append(Pause(begin, duration_ms))
    return pauses


def search_window_ms(segment_seconds: int) -> int:
    return min(PAUSE_SEARCH_WINDOW_MS, segment_seconds * 1000 // PAUSE_SEARCH_WINDOW_SHARE)


def pick_boundary(target_ms: int, low_ms: int, high_ms: int, pauses: Sequence[Pause]) -> int:
    """
    The cut point for a boundary aimed at `target_ms`, inside `[low_ms, high_ms]`: the middle of the part of the
    best pause that lies in the window. Longer pauses (up to PAUSE_SCORE_CAP_MS) and pauses closer to the target
    win; ties go to the earlier cut. Without a pause in the window the target itself is the cut.
    """
    best: tuple[float, int] | None = None
    for pause in pauses:
        begin, end = max(pause.start_ms, low_ms), min(pause.end_ms, high_ms)
        if end <= begin:
            continue
        cut = (begin + end) // 2
        score = min(pause.duration_ms, PAUSE_SCORE_CAP_MS) - abs(cut - target_ms) * PAUSE_DISTANCE_WEIGHT
        if best is None or score > best[0]:
            best = (score, cut)
    return target_ms if best is None else best[1]


class AudioSegmenter:
    """Probes and cuts audio with ffmpeg into small mono chunks that audio-input models accept."""

    def __init__(self, ffmpeg: str | None = None, ffprobe: str | None = None, timeout_seconds: float = 600.0):
        self.ffmpeg = ffmpeg or settings.ffmpeg_path
        self.ffprobe = ffprobe or settings.ffprobe_path
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def is_available() -> bool:
        return bool(shutil.which(settings.ffmpeg_path) and shutil.which(settings.ffprobe_path))

    @staticmethod
    @contextmanager
    def workspace() -> Generator[Path]:
        """A private temp directory for a download and its chunks, removed on exit even after a failure."""
        with tempfile.TemporaryDirectory(prefix='hearfolio-audio-') as path:
            yield Path(path)

    @staticmethod
    def plan(
        duration_ms: int, segment_seconds: int, pauses: Sequence[Pause] = (), *, start_ms: int = 0
    ) -> list[SegmentRange]:
        """
        Chunk ranges covering `[start_ms, duration_ms)` contiguously, indexed from 0. Each boundary aims at
        `segment_seconds` after the previous one and moves to the best pause within `search_window_ms` of it, so
        words are not cut in half; without pauses the boundaries are the plain fixed offsets. A tail shorter than
        MIN_TAIL_MS joins the previous chunk. Pure and deterministic: the same inputs give the same ranges.
        """
        if duration_ms - start_ms <= 0:
            return []
        step = segment_seconds * 1000
        window = search_window_ms(segment_seconds)
        ordered = sorted(pauses, key=lambda pause: (pause.start_ms, pause.end_ms))
        bounds = [start_ms]
        while duration_ms - (bounds[-1] + step) >= MIN_TAIL_MS:
            target = bounds[-1] + step
            low = target - window
            high = min(target + window, duration_ms - MIN_TAIL_MS)
            nearby = [pause for pause in ordered if pause.end_ms > low and pause.start_ms < high]
            bounds.append(pick_boundary(target, low, high, nearby))
        ends = [*bounds[1:], duration_ms]
        return [SegmentRange(index=i, start_ms=start, end_ms=end) for i, (start, end) in enumerate(zip(bounds, ends))]

    @staticmethod
    def needs_split(duration_ms: int, segment_seconds: int) -> bool:
        """Whether `duration_ms` of audio gives more than one chunk (only then pauses matter)."""
        return duration_ms - segment_seconds * 1000 >= MIN_TAIL_MS

    async def probe_duration_ms(self, source: Path) -> int:
        stdout = await self._run(
            [
                self.ffprobe,
                '-v',
                'error',
                *SAFE_INPUT_OPTIONS,
                '-show_entries',
                'format=duration',
                '-of',
                'json',
                str(source),
            ],
            error='Не удалось прочитать аудиофайл',
        )
        try:
            duration = float(json.loads(stdout)['format']['duration'])
        except (ValueError, KeyError, TypeError) as e:
            raise AudioProcessingError('Не удалось определить длительность аудио', detail=stdout[:300]) from e
        if duration <= 0:
            raise AudioProcessingError('Аудиофайл пустой')
        return round(duration * 1000)

    async def cut(self, source: Path, start_ms: int, end_ms: int, target_dir: Path) -> Path:
        """Re-encode `[start_ms, end_ms)` of `source` to a mono 16 kHz mp3 in `target_dir`."""
        target = target_dir / f'chunk-{start_ms}-{end_ms}.{SEGMENT_FORMAT}'
        await self._run(
            [
                self.ffmpeg,
                '-nostdin',
                '-hide_banner',
                '-v',
                'error',
                '-y',
                '-ss',
                f'{start_ms / 1000:.3f}',
                '-t',
                f'{(end_ms - start_ms) / 1000:.3f}',
                *SAFE_INPUT_OPTIONS,
                '-i',
                str(source),
                '-vn',
                '-ac',
                '1',
                '-ar',
                str(SEGMENT_SAMPLE_RATE),
                '-c:a',
                'libmp3lame',
                '-b:a',
                SEGMENT_BITRATE,
                str(target),
            ],
            error='Не удалось подготовить фрагмент аудио',
        )
        if not target.exists() or target.stat().st_size == 0:
            raise AudioProcessingError('Не удалось подготовить фрагмент аудио', detail='empty output')
        return target

    async def is_silent(self, chunk: Path) -> bool:
        """True when the chunk's peak level is below `SILENCE_MAX_VOLUME_DB`; probe failures count as not silent."""
        process = await asyncio.create_subprocess_exec(
            self.ffmpeg,
            '-nostdin',
            '-hide_banner',
            *SAFE_INPUT_OPTIONS,
            '-i',
            str(chunk),
            '-af',
            'volumedetect',
            '-f',
            'null',
            '-',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()
            return False
        match = _MAX_VOLUME_RE.search(stderr.decode('utf-8', 'replace'))
        if not match:
            return False
        value = match.group(1)
        return value == '-inf' or float(value) < SILENCE_MAX_VOLUME_DB

    async def detect_pauses(self, source: Path, duration_ms: int) -> list[Pause]:
        """
        Pauses in the whole of `source` (one decoding pass, downmixed to mono 16 kHz). Best effort: any failure
        (timeout, ffmpeg error, unexpected output) gives no pauses, and the plan falls back to fixed offsets.
        """
        filters = (
            f'aformat=channel_layouts=mono,aresample={SEGMENT_SAMPLE_RATE},'
            f'silencedetect=noise={PAUSE_NOISE_DB}dB:duration={PAUSE_MIN_SECONDS}'
        )
        try:
            process = await asyncio.create_subprocess_exec(
                self.ffmpeg,
                '-nostdin',
                '-hide_banner',
                '-nostats',
                *SAFE_INPUT_OPTIONS,
                '-i',
                str(source),
                '-vn',
                '-sn',
                '-dn',
                '-af',
                filters,
                '-f',
                'null',
                '-',
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            logger.warning('Pause detection could not start: {}', e)
            return []
        try:
            lines = await asyncio.wait_for(self._pause_lines(process), timeout=self.timeout_seconds)
            await asyncio.wait_for(process.wait(), timeout=self.timeout_seconds)
        except (TimeoutError, ValueError) as e:
            # ValueError: a log line beyond the stream reader limit.
            process.kill()
            await process.wait()
            logger.warning('Pause detection failed: {}', type(e).__name__)
            return []
        if process.returncode != 0:
            logger.warning('Pause detection exited with {}', process.returncode)
            return []
        return parse_pauses(lines, duration_ms)

    @staticmethod
    async def _pause_lines(process: asyncio.subprocess.Process) -> list[str]:
        """Only `silencedetect` lines are kept, at most two per pause, so memory stays bounded by MAX_PAUSES."""
        assert process.stderr is not None
        lines: list[str] = []
        while raw := await process.stderr.readline():
            line = raw.decode('utf-8', 'replace')
            if 'silence_' in line and len(lines) < MAX_PAUSES * 2:
                lines.append(line)
        return lines

    async def _run(self, args: list[str], *, error: str) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as e:
            raise AudioProcessingError('На сервере не установлен ffmpeg', detail=args[0]) from e
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except TimeoutError as e:
            process.kill()
            await process.wait()
            raise AudioProcessingError(error, detail='timeout') from e
        if process.returncode != 0:
            raise AudioProcessingError(error, detail=stderr.decode('utf-8', 'replace')[-500:])
        return stdout.decode('utf-8', 'replace')
