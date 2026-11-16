import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from app.domains.ai.utils.transcript_phrases import (
    MAX_PHRASE_MS,
    Phrase,
    TimedSegment,
    TimedWord,
    build_phrases,
    parse_segments,
    parse_words,
    speaker_transcript,
)

DATA = Path(__file__).parent / 'fixtures'


def _load(name: str) -> dict[str, Any]:
    return json.loads((DATA / name).read_text())


def _build(payload: dict[str, Any], offset_ms: int = 0, duration_ms: int | None = None) -> list[Phrase]:
    duration = duration_ms if duration_ms is not None else round(payload.get('duration', 60) * 1000)
    return build_phrases(
        offset_ms=offset_ms,
        duration_ms=duration,
        text=payload.get('text', ''),
        words=parse_words(payload.get('words')),
        segments=parse_segments(payload.get('segments')),
    )


def _word(text: str, start: float, end: float, speaker: str | None = None) -> TimedWord:
    return TimedWord(text, round(start * 1000), round(end * 1000), speaker)


def test_grok_words_of_one_voice_read_as_one_paragraph():
    """Live Grok STT answer without speakers: ~1.5 s pauses between sentences do not break the text apart."""
    phrases = _build(_load('grok_words.json'), offset_ms=600_000, duration_ms=19_188)
    assert [(p.start_ms, p.end_ms, p.speaker) for p in phrases] == [(600_060, 618_888, None)]
    assert phrases[0].text.startswith(
        'Привет, давай обсудим интеграцию с 1С, нам нужно запустить пилот до конца месяца.'
    )
    assert phrases[0].text.endswith('Отлично, тогда в пятницу созвонимся и проверим первые результаты.')


def test_grok_speakers_are_scoped_to_the_request():
    phrases = _build(_load('grok_diarized.json'), offset_ms=300_000, duration_ms=19_188)
    assert [p.speaker for p in phrases] == ['300000:0', '300000:1', '300000:0']
    assert [p.start_ms for p in phrases] == [300_060, 307_323, 314_866]


def test_segments_of_one_speaker_close_together_merge_into_a_paragraph():
    """Deepgram answers sentence-sized segments; here every one is speaker 0 with short gaps (end clamped to the chunk)."""
    payload = _load('deepgram_segments.json')
    phrases = _build(payload, offset_ms=1_000)
    assert len(phrases) == 1
    assert (phrases[0].start_ms, phrases[0].end_ms, phrases[0].speaker) == (1_000, 20_188, '1000:0')
    assert phrases[0].text.startswith(
        'Привет. Давай обсудим интеграцию с 1С. Нам нужно запустить пилот до конца месяца.'
    )


def test_segments_split_on_speaker_change_and_long_pauses():
    segments = [
        TimedSegment('Первый.', 0, 1_000, '0'),
        TimedSegment('Ещё.', 1_500, 2_000, '0'),
        TimedSegment('Второй.', 2_100, 3_000, '1'),
        TimedSegment('После паузы.', 6_000, 7_000, '1'),
    ]
    text = 'Первый. Ещё. Второй. После паузы.'
    phrases = build_phrases(offset_ms=0, duration_ms=10_000, text=text, segments=segments)
    assert [(p.text, p.speaker) for p in phrases] == [
        ('Первый. Ещё.', '0:0'),
        ('Второй.', '0:1'),
        ('После паузы.', '0:1'),
    ]


def test_bare_words_take_punctuation_from_the_text():
    """Qwen returns words without punctuation next to a punctuated `text`."""
    payload = _load('qwen_bare_words.json')
    assert parse_words(payload['words'])[0].text == 'Привет'
    phrases = _build(payload)
    sentences = (
        'Привет, давай обсудим интеграцию с Однес. Нам нужно запустить пилот до конца месяца.',
        'Согласен, я возьму выгрузку заказов, а остатки сделаем дельтами каждые пять минут.',
        'Отлично, тогда в пятницу созвонимся и проверим первые результаты.',
    )
    # One voice with short pauses: the three sentences read as one paragraph.
    assert [p.text for p in phrases] == [' '.join(sentences)]


def test_text_only_answer_is_one_phrase_for_the_chunk():
    assert build_phrases(offset_ms=60_000, duration_ms=60_000, text='  Просто   текст. ') == [
        Phrase(60_000, 120_000, 'Просто текст.')
    ]
    assert build_phrases(offset_ms=0, duration_ms=60_000, text='') == []


@pytest.mark.parametrize(
    'raw',
    [
        None,
        'words',
        {'word': 'a'},
        [None, 1, 'x', []],
        [{'word': 'a', 'start': 'x', 'end': 1}],
        [{'word': 'a', 'start': float('nan'), 'end': 1}],
        [{'word': 'a', 'start': -1, 'end': 1}],
        [{'word': 'a', 'start': True, 'end': 1}],
        [{'word': '   ', 'start': 0, 'end': 1}],
        [{'word': 5, 'start': 0, 'end': 1}],
        [{'start': 0, 'end': 1}],
    ],
)
def test_garbage_words_are_dropped(raw):
    assert parse_words(raw) == []
    assert build_phrases(offset_ms=0, duration_ms=10_000, text='Текст.', words=parse_words(raw)) == [
        Phrase(0, 10_000, 'Текст.')
    ]


def test_parsing_normalizes_speakers_and_skips_empty_words():
    words = parse_words(
        [
            {'word': ' Да, ', 'start': 0.5, 'end': 1.0, 'speaker': 0},
            {'word': '  ', 'start': 1.1, 'end': 1.1},
            {'word': 'нет', 'start': 1.2, 'end': 1.4, 'speaker': 'SPEAKER_01'},
            {'word': 'ок', 'start': 1.5, 'end': 1.6, 'speaker': 2.0},
            {'word': 'всё', 'start': 1.7, 'end': 1.8, 'speaker': False},
        ]
    )
    assert words == [
        TimedWord('Да,', 500, 1000, '0'),
        TimedWord('нет', 1200, 1400, 'SPEAKER_01'),
        TimedWord('ок', 1500, 1600, '2'),
        TimedWord('всё', 1700, 1800, None),
    ]
    assert parse_segments([{'text': 'x', 'start': 0, 'end': 1, 'speaker': None}, {'text': 'y'}]) == [
        TimedSegment('x', 0, 1000)
    ]


@pytest.mark.parametrize(
    'bad',
    [
        {'word': 'b', 'start': 2.0, 'end': 1.0},
        {'word': 'b', 'start': None, 'end': 1.0},
        {'word': 'b', 'start': 1.0, 'end': float('inf')},
        {'word': 'b', 'start': -0.1, 'end': 1.0},
        'b',
    ],
)
def test_one_badly_timed_word_rejects_the_word_level(bad):
    raw = [{'word': 'Раз.', 'start': 0, 'end': 0.5}, bad]
    assert parse_words(raw) == []
    segments = [TimedSegment('Раз. b', 0, 2000)]
    assert build_phrases(offset_ms=0, duration_ms=5_000, text='Раз. b', words=parse_words(raw), segments=segments) == [
        Phrase(0, 2000, 'Раз. b')
    ]


def test_speaker_change_and_pauses_split_phrases():
    words = [
        _word('Сколько', 0.0, 0.5, 'a'),
        _word('секунд?', 0.6, 1.0, 'a'),
        # 1.9 s after a sentence end: the same speaker goes on, same paragraph
        _word('Пять?', 2.9, 3.3, 'a'),
        _word('Десять?', 3.5, 4.0, 'a'),
        # 2 s after a sentence end: new paragraph
        _word('Ладно', 6.0, 6.4, 'a'),
        # 3.9 s mid-sentence: same paragraph
        _word('тогда', 10.3, 10.7, 'a'),
        # 4 s mid-sentence: new paragraph
        _word('пять', 14.7, 15.0, 'a'),
        # another speaker right away: new paragraph
        _word('Хорошо.', 15.0, 15.4, 'b'),
    ]
    text = ' '.join(word.text for word in words)
    phrases = build_phrases(offset_ms=0, duration_ms=20_000, text=text, words=words)
    assert [(p.text, p.speaker) for p in phrases] == [
        ('Сколько секунд? Пять? Десять?', '0:a'),
        ('Ладно тогда', '0:a'),
        ('пять', '0:a'),
        ('Хорошо.', '0:b'),
    ]


def test_long_phrase_splits_at_the_last_sentence_end_inside_the_cap():
    # Words every 1 s with 0.2 s gaps, sentence ends at words 39 and 84: 150 s without a pause long enough to split.
    words = [_word(f'w{i}.' if i in (39, 84) else f'w{i}', i, i + 0.8) for i in range(150)]
    phrases = build_phrases(offset_ms=0, duration_ms=160_000, text=' '.join(w.text for w in words), words=words)
    assert [p.text.split()[0] for p in phrases] == ['w0', 'w85']
    assert phrases[0].text.endswith('w84.')
    assert all(p.end_ms - p.start_ms <= MAX_PHRASE_MS for p in phrases)


def test_long_phrase_without_sentence_end_splits_at_the_largest_gap():
    words = [_word(f'w{i}', i, i + (0.5 if i == 40 else 0.9)) for i in range(120)]
    phrases = build_phrases(offset_ms=0, duration_ms=130_000, text=' '.join(w.text for w in words), words=words)
    assert phrases[0].text.split()[-1] == 'w40'
    assert phrases[1].text.split()[0] == 'w41'
    assert all(p.end_ms - p.start_ms <= MAX_PHRASE_MS for p in phrases)


def test_times_are_clamped_ordered_and_never_overlap():
    words = [
        _word('Раз.', 0.0, 1.0),
        # starts before the previous word: moved forward
        _word('Два.', 0.5, 0.7),
        _word('Три.', 3.0, 4.0),
        # beyond the chunk end
        _word('Четыре.', 9.5, 12.0),
    ]
    phrases = build_phrases(offset_ms=10_000, duration_ms=10_000, text='Раз. Два. Три. Четыре.', words=words)
    assert [(p.start_ms, p.end_ms, p.text) for p in phrases] == [
        (10_000, 11_000, 'Раз. Два.'),
        (13_000, 14_000, 'Три.'),
        (19_500, 20_000, 'Четыре.'),
    ]
    for earlier, later in itertools.pairwise(phrases):
        assert earlier.start_ms <= earlier.end_ms <= later.start_ms


def test_coverage_counts_words_not_letters():
    # Same letters, different words: one of three words is missing, so the words level is not trusted.
    words = [_word('Привет.', 0, 0.5), _word('Мир.', 1, 1.5)]
    text = 'Привет. Мир. Привет.'
    assert build_phrases(offset_ms=0, duration_ms=5_000, text=text, words=words) == [Phrase(0, 5_000, text)]
    # Case and punctuation do not matter.
    words = [_word('привет', 0, 0.5), _word('мир!', 1, 1.5), _word('Ещё', 2, 2.5)]
    phrases = build_phrases(offset_ms=0, duration_ms=5_000, text='Привет, мир. Ещё —', words=words)
    assert len(phrases) == 1 and phrases[0].end_ms == 2500


def test_missing_words_fall_back_to_the_provider_text():
    words = [_word('Привет.', 0, 0.5)]
    text = 'Привет. Здесь было ещё много слов, которых нет в списке.'
    assert build_phrases(offset_ms=0, duration_ms=5_000, text=text, words=words) == [Phrase(0, 5_000, text)]


def test_incomplete_segments_fall_back_to_the_provider_text():
    segments = [TimedSegment('Начало', 0, 1000)]
    text = 'Начало длинной речи, которой нет в сегментах.'
    assert build_phrases(offset_ms=0, duration_ms=5_000, text=text, segments=segments) == [Phrase(0, 5_000, text)]


def test_words_without_speaker_take_it_from_labelled_segments():
    words = [_word('Да.', 0, 0.5), _word('Нет.', 2.0, 2.5, '7'), _word('Ну.', 4.0, 4.5)]
    segments = [TimedSegment('Да.', 0, 1000, '0'), TimedSegment('Нет. Ну.', 1900, 4600, '1')]
    phrases = build_phrases(offset_ms=0, duration_ms=5_000, text='Да. Нет. Ну.', words=words, segments=segments)
    # A word's own speaker wins; the others take their segment's.
    assert [(p.text, p.speaker) for p in phrases] == [('Да.', '0:0'), ('Нет.', '0:7'), ('Ну.', '0:1')]


def test_without_text_the_richest_level_is_used():
    words = [_word('Слово', 0, 0.5)]
    assert build_phrases(offset_ms=0, duration_ms=5_000, text='', words=words) == [Phrase(0, 500, 'Слово')]


def test_speaker_transcript_labels_one_request_and_merges_turns():
    segments = [
        {'start_ms': 0, 'end_ms': 1, 'text': 'Привет.', 'speaker': '0:1'},
        {'start_ms': 1, 'end_ms': 2, 'text': 'Как дела?', 'speaker': '0:1'},
        {'start_ms': 2, 'end_ms': 3, 'text': 'Хорошо.', 'speaker': '0:0'},
        {'start_ms': 3, 'end_ms': 4, 'text': '', 'speaker': '0:1'},
        {'start_ms': 4, 'end_ms': 5, 'text': 'Без метки.'},
        'garbage',
    ]
    assert speaker_transcript(segments) == 'Спикер 1: Привет. Как дела?\nСпикер 2: Хорошо.\nБез метки.'


@pytest.mark.parametrize(
    'segments',
    [
        [],
        None,
        [{'text': 'a'}, {'text': 'b'}],
        # one speaker: labels add nothing
        [{'text': 'a', 'speaker': '0:0'}, {'text': 'b', 'speaker': '0:0'}],
        # two requests: their speaker ids are not comparable
        [{'text': 'a', 'speaker': '0:0'}, {'text': 'b', 'speaker': '0:1'}, {'text': 'c', 'speaker': '60000:0'}],
    ],
)
def test_speaker_transcript_is_none_when_speakers_are_not_comparable(segments):
    assert speaker_transcript(segments) is None
