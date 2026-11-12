import asyncio
import json
import re
import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

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

_MAX_VOLUME_RE = re.compile(r'max_volume:\s*(-?[\d.]+|-inf)\s*dB')


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
    def plan(duration_ms: int, segment_seconds: int) -> list[SegmentRange]:
        """Deterministic chunk boundaries: the same duration and length always give the same ranges (resume relies on it)."""
        if duration_ms <= 0:
            return []
        step = segment_seconds * 1000
        bounds = list(range(0, duration_ms, step))
        if len(bounds) > 1 and duration_ms - bounds[-1] < MIN_TAIL_MS:
            bounds.pop()
        ends = [*bounds[1:], duration_ms]
        return [SegmentRange(index=i, start_ms=start, end_ms=end) for i, (start, end) in enumerate(zip(bounds, ends))]

    async def probe_duration_ms(self, source: Path) -> int:
        stdout = await self._run(
            [
                self.ffprobe,
                '-v',
                'error',
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
