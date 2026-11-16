"""
Timed, speaker-aware phrases from a speech-to-text answer (`verbose_json`: `words`, `segments`, `text`).

Pure functions, mirrored by the desktop/Android app: the rules and thresholds below must stay identical on both sides.
Parsing never raises: malformed entries are dropped, and `build_phrases` falls back from words to segments to one
coarse phrase for the whole chunk, so a model that returns plain text keeps working exactly as before.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

# Phrases are paragraphs: one speaker's continuous speech reads as one text. A pause this long after a sentence end
# starts a new phrase; a pause this long starts one regardless (a thought cut mid-sentence by a long silence).
SENTENCE_PAUSE_MS = 2000
HARD_PAUSE_MS = 4000
# Longer phrases are split at their last sentence end inside the limit, else at the largest gap inside it, so a
# monologue still gets timestamps to jump to.
MAX_PHRASE_MS = 90_000
# Words (or segments) must carry at least this share of the words of the provider's `text` (multiset, case and
# punctuation ignored); otherwise words were lost and the provider's text wins as one coarse phrase.
MIN_COVERAGE = 0.9
SENTENCE_ENDS = ('.', '?', '!', '…')
# Closing quotes and brackets after a sentence end: `«Готово.»` still ends a sentence.
_TRAILING_CLOSERS = '"\'»”)]'
# Bound on parsed entries: a 3-hour chunk has ~40k words.
MAX_ENTRIES = 200_000


@dataclass(frozen=True)
class TimedWord:
    """A word with times in ms relative to the start of the audio sent; `speaker` is the provider's raw label."""

    text: str
    start_ms: int
    end_ms: int
    speaker: str | None = None


@dataclass(frozen=True)
class TimedSegment:
    text: str
    start_ms: int
    end_ms: int
    speaker: str | None = None


@dataclass(frozen=True)
class Phrase:
    """A transcript segment with absolute times (ms from the start of the recording)."""

    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None


# ----- parsing -----


def _ms(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return round(value * 1000)


def _speaker(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    if isinstance(value, str) and value.strip():
        return value.strip()[:64]
    return None


def _timed(item: Any, text_key: str) -> tuple[str, int, int, str | None] | None:
    if not isinstance(item, dict):
        return None
    text = item.get(text_key)
    start, end = _ms(item.get('start')), _ms(item.get('end'))
    if not isinstance(text, str) or not text.strip() or start is None or end is None or end < start:
        return None
    return ' '.join(text.split()), start, end, _speaker(item.get('speaker'))


def parse_words(raw: Any) -> list[TimedWord]:
    """
    `words[{word, start, end, speaker?}]` (seconds) in provider order. Words with empty text are skipped; one word
    with a missing, non-finite, negative or reversed time (or a non-object entry) rejects the whole list, since its
    timing can no longer be trusted.
    """
    if not isinstance(raw, list):
        return []
    words = []
    for item in raw[:MAX_ENTRIES]:
        if isinstance(item, dict) and not (isinstance(item.get('word'), str) and item['word'].strip()):
            continue
        parsed = _timed(item, 'word')
        if parsed is None:
            return []
        words.append(TimedWord(*parsed))
    return words


def parse_segments(raw: Any) -> list[TimedSegment]:
    """`segments[{text, start, end, speaker?}]` (seconds) in provider order; invalid entries are dropped."""
    if not isinstance(raw, list):
        return []
    segments = []
    for item in raw[:MAX_ENTRIES]:
        if (parsed := _timed(item, 'text')) is not None:
            segments.append(TimedSegment(*parsed))
    return segments


# ----- helpers -----


def _tokens(text: str) -> Counter[str]:
    """Words compared case- and punctuation-insensitively (letters and digits only)."""
    return Counter(token for word in text.split() if (token := ''.join(c for c in word.casefold() if c.isalnum())))


def _covers(parts: Sequence[str], text: str) -> bool:
    """Whether `parts` carry at least MIN_COVERAGE of the words of `text` (as a multiset)."""
    expected = _tokens(text)
    total = sum(expected.values())
    if total == 0:
        return True
    found = _tokens(' '.join(parts))
    return sum((expected & found).values()) >= total * MIN_COVERAGE


def ends_sentence(text: str) -> bool:
    return text.rstrip(_TRAILING_CLOSERS).endswith(SENTENCE_ENDS)


def scoped_speaker(scope_ms: int, speaker: str | None) -> str | None:
    """
    Provider speaker ids mean something only inside one request, so the stored label names the request (its start
    in ms from the start of the recording): `0:1` is speaker 1 of the request that began at 0 ms.
    """
    return None if speaker is None else f'{scope_ms}:{speaker}'


def _repunctuate(words: list[TimedWord], text: str) -> list[TimedWord]:
    """
    Some models return bare words (no punctuation, other casing) next to a punctuated `text`. When the text splits
    into exactly the same words (letters and digits compared), its tokens replace the word texts.
    """
    tokens = text.split()
    if len(tokens) != len(words) or any(_tokens(t) != _tokens(w.text) for t, w in zip(tokens, words, strict=True)):
        return words
    return [replace(word, text=token) for word, token in zip(words, tokens, strict=True)]


def _speakers_from_segments(words: list[TimedWord], segments: list[TimedSegment]) -> list[TimedWord]:
    """A word without a speaker takes the speaker of the labelled segment containing its middle, if any."""
    labelled = [segment for segment in segments if segment.speaker is not None]
    if not labelled:
        return words
    result = []
    for word in words:
        if word.speaker is None:
            middle = (word.start_ms + word.end_ms) / 2
            owner = next((s for s in labelled if s.start_ms <= middle <= s.end_ms), None)
            if owner is not None:
                word = replace(word, speaker=owner.speaker)
        result.append(word)
    return result


def _monotonic(words: list[TimedWord]) -> list[TimedWord]:
    """Times never go back: a word starting before the previous one starts where that one starts."""
    result: list[TimedWord] = []
    for word in words:
        if result and word.start_ms < result[-1].start_ms:
            word = replace(word, start_ms=result[-1].start_ms, end_ms=max(word.end_ms, result[-1].start_ms))
        result.append(word)
    return result


def _group(words: list[TimedWord]) -> list[list[TimedWord]]:
    groups = [[words[0]]]
    for word in words[1:]:
        previous = groups[-1][-1]
        gap = word.start_ms - previous.end_ms
        if (
            word.speaker != previous.speaker
            or gap >= HARD_PAUSE_MS
            or (gap >= SENTENCE_PAUSE_MS and ends_sentence(previous.text))
        ):
            groups.append([word])
        else:
            groups[-1].append(word)
    return groups


def _split_long(group: list[TimedWord]) -> list[list[TimedWord]]:
    result = []
    while len(group) > 1 and group[-1].end_ms - group[0].start_ms > MAX_PHRASE_MS:
        limit = group[0].start_ms + MAX_PHRASE_MS
        # Cut before word i (1..n-1) when the part before it fits the limit; the first word always fits as a part.
        candidates = [i for i in range(1, len(group)) if group[i - 1].end_ms <= limit] or [1]
        sentence_cuts = [i for i in candidates if ends_sentence(group[i - 1].text)]
        if sentence_cuts:
            cut = sentence_cuts[-1]
        else:
            cut = max(candidates, key=lambda i: (group[i].start_ms - group[i - 1].end_ms, i))
        result.append(group[:cut])
        group = group[cut:]
    result.append(group)
    return result


def _place(phrases: list[Phrase], offset_ms: int, duration_ms: int) -> list[Phrase]:
    """Absolute times, clamped to the chunk, in order, never overlapping or negative; empty texts dropped."""
    low, high = offset_ms, offset_ms + max(duration_ms, 0)
    result: list[Phrase] = []
    for phrase in phrases:
        text = phrase.text.strip()
        if not text:
            continue
        start = min(max(offset_ms + phrase.start_ms, low), high)
        end = min(max(offset_ms + phrase.end_ms, low), high)
        if result:
            start = max(start, result[-1].end_ms)
        result.append(Phrase(start, max(start, end), text, phrase.speaker))
    return result


def _scoped(phrases: list[Phrase], offset_ms: int) -> list[Phrase]:
    return [replace(phrase, speaker=scoped_speaker(offset_ms, phrase.speaker)) for phrase in phrases]


# ----- building -----


def phrases_from_words(words: Sequence[TimedWord]) -> list[Phrase]:
    """Group timed units (words or provider segments; relative times) into paragraphs: speaker change, pauses,
    MAX_PHRASE_MS cap."""
    ordered = _monotonic(list(words))
    if not ordered:
        return []
    phrases = []
    for group in _group(ordered):
        for part in _split_long(group):
            text = ' '.join(word.text for word in part)
            phrases.append(Phrase(part[0].start_ms, max(word.end_ms for word in part), text, part[0].speaker))
    return phrases


def build_phrases(
    *,
    offset_ms: int,
    duration_ms: int,
    text: str,
    words: Sequence[TimedWord] = (),
    segments: Sequence[TimedSegment] = (),
) -> list[Phrase]:
    """
    Phrases for one request whose audio starts at `offset_ms` of the recording and lasts `duration_ms`.
    1. Words with times → paragraphs (speaker change; a pause ≥ SENTENCE_PAUSE_MS after `.?!…` or ≥ HARD_PAUSE_MS;
       split above MAX_PHRASE_MS).
    2. Else segments with times, grouped by the same rules (a provider's segments are often single sentences).
    3. Else one phrase for the whole chunk with `text` (today's behaviour).
    A level whose text misses words of `text` (MIN_COVERAGE) is skipped. Speakers are scoped to the request.
    """
    text = ' '.join((text or '').split())
    words = list(words)
    segments = list(segments)
    if words:
        words = _speakers_from_segments(_repunctuate(words, text), segments)
        phrases = _place(phrases_from_words(words), offset_ms, duration_ms)
        if phrases and _covers([phrase.text for phrase in phrases], text):
            return _scoped(phrases, offset_ms)
    if segments:
        units = [TimedWord(s.text, s.start_ms, s.end_ms, s.speaker) for s in segments]
        phrases = _place(phrases_from_words(units), offset_ms, duration_ms)
        if phrases and _covers([phrase.text for phrase in phrases], text):
            return _scoped(phrases, offset_ms)
    if not text:
        return []
    return [Phrase(offset_ms, offset_ms + max(duration_ms, 0), text)]


# ----- reading stored segments -----


def speaker_transcript(segments: Any) -> str | None:
    """
    The transcript as `Спикер N: …` lines for text models, or `None` when speakers are unknown or not comparable:
    only labels from one request (one scope) are the same people throughout, so a transcript stitched from several
    requests, or with fewer than two speakers, stays plain text.
    """
    rows = [
        (
            str(segment.get('speaker')) if segment.get('speaker') is not None else None,
            str(segment.get('text', '')).strip(),
        )
        for segment in segments or []
        if isinstance(segment, dict)
    ]
    labels = list(dict.fromkeys(label for label, text in rows if label is not None and text))
    scopes = {label.rsplit(':', 1)[0] if ':' in label else '' for label in labels}
    if len(labels) < 2 or len(scopes) != 1:
        return None
    names = {label: f'Спикер {number}' for number, label in enumerate(labels, start=1)}
    lines: list[str] = []
    current: str | None = None
    for label, text in rows:
        if not text:
            continue
        if label is not None and label == current and lines:
            lines[-1] += f' {text}'
            continue
        current = label
        lines.append(f'{names[label]}: {text}' if label is not None else text)
    return '\n'.join(lines)
