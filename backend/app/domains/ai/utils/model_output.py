"""Parsers for model output: tolerant of code fences, labels, quotes, chatter around JSON and stray markers."""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.domains.ai.prompts import NO_SPEECH_MARKER

TITLE_MAX_LENGTH = 80
TAG_MAX_LENGTH = 40
PROJECT_MIN_CONFIDENCE = 0.6

_FENCE_RE = re.compile(r'^\s*```[\w-]*\s*\n?(.*?)\n?\s*```\s*$', re.DOTALL)
_TRANSCRIPT_LABEL_RE = re.compile(
    r'^\s*\**\s*(?:transcript(?:ion)?|расшифровка|транскрипт(?:ция)?|текст)\s*\**\s*:\s*\**\s*', re.IGNORECASE
)
_TITLE_LABEL_RE = re.compile(r'^\s*\**\s*(?:title|заголовок|название)\s*\**\s*:\s*\**\s*', re.IGNORECASE)
_QUOTES = '"\'«»“”„`*_'


def strip_code_fence(text: str) -> str:
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text


def clean_transcript(text: str) -> str:
    """Model output → transcript text; `''` means the model reported no speech."""
    text = strip_code_fence(text.strip()).strip()
    text = _TRANSCRIPT_LABEL_RE.sub('', text, count=1).strip()
    if text.strip(' .').upper() == NO_SPEECH_MARKER:
        return ''
    # The marker sometimes trails real text; drop it, keep the speech.
    text = re.sub(rf'\s*\b{NO_SPEECH_MARKER}\b\s*', ' ', text).strip()
    return text


def clean_title(text: str) -> str | None:
    text = strip_code_fence(text.strip())
    line = next((line.strip() for line in text.splitlines() if line.strip()), '')
    line = line.lstrip('#').strip()
    line = _TITLE_LABEL_RE.sub('', line, count=1).strip().strip(_QUOTES).strip()
    line = re.sub(r'\s+', ' ', line).rstrip('.').strip()
    if not line:
        return None
    if len(line) > TITLE_MAX_LENGTH:
        cut = line[: TITLE_MAX_LENGTH - 1]
        line = (cut.rsplit(' ', 1)[0] if ' ' in cut else cut).rstrip(' ,;:-—') + '…'
    return line


def extract_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in `text`, ignoring fences and prose around it."""
    text = strip_code_fence(text.strip())
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != '{':
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


@dataclass
class ClassificationResult:
    tags: list[str] = field(default_factory=list)
    project: str | None = None
    project_confidence: float = 0.0


def _normalize_tag(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    tag = re.sub(r'\s+', ' ', value.strip().lstrip('#').strip(_QUOTES).strip())
    if not tag or len(tag) > TAG_MAX_LENGTH:
        return None
    return tag


def parse_classification(
    text: str, existing_tags: list[str], projects: list[str], *, max_tags: int = 5
) -> ClassificationResult:
    """
    Tags: existing names win case-insensitively (their spelling is kept), new ones are trimmed and de-duplicated.
    Project: only a name from `projects`, and only with confidence ≥ PROJECT_MIN_CONFIDENCE.
    """
    data = extract_json_object(text) or {}
    raw_tags = data.get('tags')
    if isinstance(raw_tags, str):
        raw_tags = [part for part in re.split(r'[,;\n]', raw_tags)]
    known = {tag.casefold(): tag for tag in existing_tags}
    tags: list[str] = []
    seen: set[str] = set()
    for raw in raw_tags if isinstance(raw_tags, list) else []:
        tag = _normalize_tag(raw)
        if tag is None or tag.casefold() in seen:
            continue
        seen.add(tag.casefold())
        tags.append(known.get(tag.casefold(), tag))
        if len(tags) >= max_tags:
            break

    confidence = data.get('project_confidence', data.get('confidence'))
    try:
        confidence_value = min(max(float(confidence), 0.0), 1.0) if confidence is not None else 0.0
    except TypeError, ValueError:
        confidence_value = 0.0
    project = None
    raw_project = data.get('project')
    if isinstance(raw_project, str) and confidence_value >= PROJECT_MIN_CONFIDENCE:
        by_name = {name.casefold(): name for name in projects}
        project = by_name.get(raw_project.strip().strip(_QUOTES).strip().casefold())
    return ClassificationResult(tags=tags, project=project, project_confidence=confidence_value if project else 0.0)


def transcript_excerpt(text: str, limit: int = 16000) -> str:
    """Head and tail of a long transcript: enough for a title or tags without paying for the whole text."""
    if len(text) <= limit:
        return text
    head = int(limit * 0.75)
    return f'{text[:head]}\n[…]\n{text[-(limit - head) :]}'
