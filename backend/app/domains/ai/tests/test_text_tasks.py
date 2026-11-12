import pytest

from app.domains.ai.services.openrouter_client import AIErrorCode, AIProviderError, OpenRouterClient
from app.domains.ai.services.text_task_service import TextTaskService
from app.domains.ai.tests.fakes import FakeProvider, chat_reply, error_reply, no_sleep
from app.domains.ai.utils.model_output import (
    clean_title,
    clean_transcript,
    extract_json_object,
    parse_classification,
    transcript_excerpt,
)


def make_service(provider: FakeProvider) -> TextTaskService:
    client = OpenRouterClient('https://router.test/api/v1', 'key', transport=provider.transport, sleep=no_sleep)
    return TextTaskService(client, 'test/text')


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('Планирование релиза 2.0', 'Планирование релиза 2.0'),
        ('"Планирование релиза."', 'Планирование релиза'),
        ('Заголовок: «Бюджет на Q3»\n\nОбъяснение…', 'Бюджет на Q3'),
        ('**Title:** Hiring plan', 'Hiring plan'),
        ('# Созвон с клиентом', 'Созвон с клиентом'),
        ('```\nОбзор\n```', 'Обзор'),
        ('   ', None),
    ],
)
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


def test_clean_title_caps_length_on_a_word_boundary():
    title = clean_title('слово ' * 40)
    assert title is not None
    assert len(title) <= 80
    assert title.endswith('…')
    assert 'слов…' not in title


def test_clean_transcript():
    assert clean_transcript('Transcript: Привет, мир') == 'Привет, мир'
    assert clean_transcript(' NO_SPEECH. ') == ''
    assert clean_transcript('Да. NO_SPEECH') == 'Да.'


def test_extract_json_from_messy_output():
    assert extract_json_object('```json\n{"tags": ["a"]}\n```') == {'tags': ['a']}
    assert extract_json_object('Конечно! Вот ответ: {"project": null} Надеюсь, помог.') == {'project': None}
    assert extract_json_object('нет json') is None


def test_parse_classification_reuses_existing_tags_and_known_projects():
    result = parse_classification(
        '{"tags": ["#Клиент Альфа", "клиент альфа", "Бюджет", "", 5, "x' + 'y' * 60 + '"], '
        '"project": "  проект альфа ", "project_confidence": 0.9}',
        existing_tags=['Клиент Альфа'],
        projects=['Проект Альфа', 'Внутреннее'],
    )
    assert result.tags == ['Клиент Альфа', 'Бюджет']
    assert result.project == 'Проект Альфа'
    assert result.project_confidence == 0.9


def test_parse_classification_ignores_unknown_or_unsure_projects():
    assert parse_classification('{"project": "Новый", "project_confidence": 1}', [], ['Старый']).project is None
    assert parse_classification('{"project": "Старый", "project_confidence": 0.3}', [], ['Старый']).project is None
    assert parse_classification('{"project": "Старый", "project_confidence": "high"}', [], ['Старый']).project is None
    assert parse_classification('garbage', [], ['Старый']).tags == []


def test_parse_classification_limits_tag_count_and_accepts_a_string():
    result = parse_classification('{"tags": "a, b, c, d, e, f"}', [], [], max_tags=5)
    assert result.tags == ['a', 'b', 'c', 'd', 'e']


def test_transcript_excerpt_keeps_head_and_tail():
    text = 'a' * 10_000 + 'b' * 10_000
    excerpt = transcript_excerpt(text, 1000)
    assert excerpt.startswith('a' * 750)
    assert excerpt.endswith('b' * 250)


@pytest.mark.asyncio
async def test_generate_title():
    provider = FakeProvider().add('/chat/completions', chat_reply('«Ретро спринта 14»'))
    assert await make_service(provider).generate_title('Обсуждаем ретро спринта...') == 'Ретро спринта 14'


@pytest.mark.asyncio
async def test_classify_falls_back_when_json_mode_is_rejected():
    provider = FakeProvider().add(
        '/chat/completions',
        error_reply(400, 'response_format is not supported'),
        chat_reply('Ответ: {"tags": ["найм"], "project": "HR", "project_confidence": 0.8}'),
    )
    result = await make_service(provider).classify('Говорим про найм', ['Найм'], ['HR'])
    assert result.tags == ['Найм']
    assert result.project == 'HR'
    bodies = provider.bodies('/chat/completions')
    assert bodies[0]['response_format'] == {'type': 'json_object'}
    assert 'response_format' not in bodies[1]


@pytest.mark.asyncio
async def test_summary_rejects_cut_off_answer():
    provider = FakeProvider().add('/chat/completions', chat_reply('- пункт', finish_reason='length'))
    with pytest.raises(AIProviderError) as raised:
        await make_service(provider).summarize('текст', 'Кратко')
    assert raised.value.code == AIErrorCode.INCOMPLETE


@pytest.mark.asyncio
async def test_summary_sends_instruction_and_transcript():
    provider = FakeProvider().add('/chat/completions', chat_reply('## Итоги\n- решили'))
    text = await make_service(provider).summarize('полный текст встречи', 'Выпиши решения', title='Планёрка')
    assert text == '## Итоги\n- решили'
    content = provider.bodies('/chat/completions')[0]['messages'][1]['content']
    assert 'Выпиши решения' in content
    assert 'полный текст встречи' in content
    assert 'Планёрка' in content
