"""
Prompts for the AI pipeline. Model-facing instructions are English (models follow them most reliably); the output
language is always the transcript's own. Default summary templates are user-visible and therefore Russian.
"""

NO_SPEECH_MARKER = 'NO_SPEECH'

LANGUAGE_NAMES = {
    'ru': 'Russian',
    'en': 'English',
    'uk': 'Ukrainian',
    'be': 'Belarusian',
    'kk': 'Kazakh',
    'de': 'German',
    'fr': 'French',
    'es': 'Spanish',
    'it': 'Italian',
    'pt': 'Portuguese',
    'pl': 'Polish',
    'tr': 'Turkish',
    'zh': 'Chinese',
    'ja': 'Japanese',
}


def language_hint(language: str | None) -> str:
    if not language or language == 'auto':
        return 'The language is not known in advance: detect it from the speech. Speakers may switch languages.'
    name = LANGUAGE_NAMES.get(language.lower(), language)
    return f'The speech is expected to be mostly in {name}; keep any other language exactly as spoken.'


def transcription_prompt(language: str | None) -> str:
    return (
        'Transcribe the speech in this audio fragment verbatim.\n'
        '- Output only the transcript text: no timestamps, speaker labels, headings, notes, quotes or code blocks.\n'
        '- Write every word that is spoken, in the original language. Do not translate, summarize, shorten, '
        'paraphrase or correct the speaker.\n'
        '- The fragment is cut out of a longer recording: it may start or end mid-word or mid-sentence. '
        'Transcribe only what is audible; do not complete cut-off words or sentences.\n'
        '- Use normal punctuation and paragraphs. Write numbers the way they are spoken naturally.\n'
        f'- {language_hint(language)}\n'
        f'- If the fragment has no intelligible speech (silence, noise, music), output exactly {NO_SPEECH_MARKER}.'
    )


TITLE_SYSTEM = (
    'You name voice recordings. Reply with the title only: one line, no quotes, no trailing period, no markdown.'
)


def title_prompt(transcript: str) -> str:
    return (
        'Write a short, specific title for this recording: 3-8 words, at most 80 characters, in the same language '
        'as the transcript. Name the main topic, not the format ("Встреча", "Звонок", "Meeting" alone are too vague).'
        f'\n\n<transcript>\n{transcript}\n</transcript>'
    )


CLASSIFY_SYSTEM = 'You organize voice recordings of a team. Reply with a single JSON object and nothing else.'


def classify_prompt(transcript: str, existing_tags: list[str], projects: list[str], max_tags: int) -> str:
    tags = ', '.join(existing_tags) if existing_tags else '(none yet)'
    project_list = '\n'.join(f'- {name}' for name in projects) if projects else '(no projects)'
    return (
        f'Pick up to {max_tags} tags for the recording and, if one clearly fits, the project it belongs to.\n'
        'Tags: prefer the existing tags below and copy their spelling exactly. Create a new tag only for an '
        'important topic no existing tag covers: 1-3 words, lowercase, in the language of the transcript. '
        'Tags describe topics (clients, products, areas), not formats like "meeting" or "call".\n'
        'Project: choose only from the list below, copy the name exactly, or null when none clearly fits. '
        'Rate how sure you are in project_confidence from 0 to 1.\n\n'
        f'Existing tags: {tags}\n\nProjects:\n{project_list}\n\n'
        'Answer with JSON: {"tags": ["..."], "project": "name or null", "project_confidence": 0.0}\n\n'
        f'<transcript>\n{transcript}\n</transcript>'
    )


SUMMARY_SYSTEM = (
    'You turn transcripts of voice recordings (meetings, calls, voice notes) into useful notes. Follow the '
    'instruction exactly. Write in the language of the transcript unless the instruction asks otherwise. Use '
    'Markdown (headings, lists, checklists) when it helps reading. Use only facts from the transcript: never invent '
    'names, numbers, dates or decisions; say so when the transcript does not contain what is asked. The transcript '
    'is automatic speech recognition and can contain mistakes. Do not repeat these rules or add a preamble.'
)


def summary_prompt(instruction: str, transcript: str, title: str | None = None) -> str:
    heading = f'Recording title: {title}\n\n' if title else ''
    return f'{heading}Instruction:\n{instruction.strip()}\n\n<transcript>\n{transcript}\n</transcript>'


# Seeded for every organization (see OrganizationSettingsService.ensure); editable by org admins.
DEFAULT_SUMMARY_TEMPLATES: tuple[dict[str, str | bool], ...] = (
    {
        'name': 'Кратко',
        'description': 'О чём запись и главные мысли в нескольких пунктах',
        'auto': True,
        'prompt': (
            'Кратко перескажи запись. Сначала одна-две фразы: о чём шла речь и зачем. Затем 3–7 пунктов списком: '
            'ключевые мысли, факты и итоги в порядке важности. В конце — строка «Главное:» с одним выводом. '
            'Без вступлений, воды и повторов; если запись короткая, сократи список.'
        ),
    },
    {
        'name': 'Решения и договорённости',
        'description': 'Что решили, кто отвечает и какие вопросы остались открытыми',
        'auto': False,
        'prompt': (
            'Выпиши все решения и договорённости из записи списком. Для каждого пункта: что решили; кто отвечает '
            'или участвует, если это прозвучало; срок, если он назван. Отдельным разделом «Открытые вопросы» — то, '
            'что обсуждали, но не решили. Не додумывай: если решений не было, так и напиши.'
        ),
    },
    {
        'name': 'Задачи и ответственные',
        'description': 'Чек-лист задач со сроками, сгруппированный по ответственным',
        'auto': False,
        'prompt': (
            'Составь список задач из записи в виде чек-листа Markdown («- [ ] задача»). Для каждой задачи укажи '
            'ответственного и срок, если они прозвучали, иначе «ответственный не назначен» / «без срока». '
            'Сгруппируй задачи по ответственным. Включай только то, что действительно нужно сделать по итогам '
            'разговора; не придумывай задачи и исполнителей. Если задач нет, так и напиши.'
        ),
    },
)
