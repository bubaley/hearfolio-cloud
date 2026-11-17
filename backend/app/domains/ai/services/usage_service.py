"""
AI spending: one `AIUsage` row per provider request, from the provider's own measurements (tokens, audio seconds,
`usage.cost` in USD). Nothing is estimated; reports say how many requests had no reported cost.
"""

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from loguru import logger

from app.domains.ai.models import AIUsage, AIUsageKind, RecordingResult
from app.domains.user.models import User

MAX_COUNT = 2**62


def _count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= MAX_COUNT else None


def _cost(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        cost = Decimal(str(value))
    except InvalidOperation:
        return None
    return cost if cost.is_finite() and Decimal(0) <= cost < Decimal(10**9) else None


def measured(usage: dict[str, Any]) -> dict[str, Any]:
    """Provider `usage` → AIUsage fields: chat tokens (with reasoning and cached parts) or transcription seconds."""
    completion = usage.get('completion_tokens_details')
    prompt = usage.get('prompt_tokens_details')
    seconds = usage.get('seconds')
    audio_ms = (
        round(seconds * 1000)
        if isinstance(seconds, int | float)
        and not isinstance(seconds, bool)
        and math.isfinite(seconds)
        and seconds >= 0
        else None
    )
    return {
        'input_tokens': _count(usage.get('prompt_tokens')),
        'output_tokens': _count(usage.get('completion_tokens')),
        'reasoning_tokens': _count(completion.get('reasoning_tokens')) if isinstance(completion, dict) else None,
        'cached_tokens': _count(prompt.get('cached_tokens')) if isinstance(prompt, dict) else None,
        'audio_ms': audio_ms,
        'cost_usd': _cost(usage.get('cost')),
    }


@dataclass
class UsageRecorder:
    """
    The `on_usage` hook of an OpenRouter client: who pays and what for. `kind` (and `result_id`) may change between
    requests of one client, e.g. per post-processing step.
    """

    organization_id: UUID
    kind: AIUsageKind
    recording_id: UUID | None = None
    result_id: UUID | None = None
    user_id: UUID | None = None

    async def __call__(self, model: str, usage: dict[str, Any]) -> None:
        try:
            await AIUsage.create(
                organization_id=self.organization_id,
                recording_id=self.recording_id,
                result_id=self.result_id,
                user_id=self.user_id,
                kind=self.kind,
                model=model[:255],
                **measured(usage),
            )
        except Exception:
            logger.exception('Could not save AI usage of {} for recording {}', self.kind, self.recording_id)


# ----- reports -----

# Order of the lines of one recording: what the user sees first
KIND_ORDER = [
    AIUsageKind.TRANSCRIPTION,
    AIUsageKind.SUMMARY,
    AIUsageKind.TITLE,
    AIUsageKind.TAGS,
    AIUsageKind.SPEAKERS,
]
USAGE_FIELDS = (
    'recording_id',
    'result_id',
    'user_id',
    'kind',
    'model',
    'input_tokens',
    'output_tokens',
    'reasoning_tokens',
    'audio_ms',
    'cost_usd',
)
DELETED_SUMMARY = 'Удалённое саммари'
DELETED_USER = 'Удалённый пользователь'


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    costs = [row['cost_usd'] for row in rows if row['cost_usd'] is not None]
    return {
        'requests': len(rows),
        'input_tokens': sum(row['input_tokens'] or 0 for row in rows),
        'output_tokens': sum(row['output_tokens'] or 0 for row in rows),
        'reasoning_tokens': sum(row['reasoning_tokens'] or 0 for row in rows),
        'audio_ms': sum(row['audio_ms'] or 0 for row in rows),
        'cost_usd': float(sum(costs, Decimal(0))),
        'unknown_cost_requests': len(rows) - len(costs),
    }


def _cost_sum(rows: list[dict[str, Any]]) -> float:
    return float(sum((row['cost_usd'] for row in rows if row['cost_usd'] is not None), Decimal(0)))


class UsageReportService:
    @staticmethod
    async def recording(recording_id: UUID) -> dict[str, Any]:
        """Spending on one recording: transcription, each summary, then the small steps."""
        rows = await AIUsage.filter(recording_id=recording_id).order_by('created_at').values(*USAGE_FIELDS)
        titles = dict(
            await RecordingResult.filter(id__in={row['result_id'] for row in rows if row['result_id']}).values_list(
                'id', 'title'
            )
        )
        groups: dict[tuple[AIUsageKind, UUID | None], list[dict[str, Any]]] = {}
        for row in rows:
            kind = AIUsageKind(row['kind'])
            key = (kind, row['result_id'] if kind == AIUsageKind.SUMMARY else None)
            groups.setdefault(key, []).append(row)
        lines = [
            {
                **_totals(group),
                'kind': kind,
                'result_id': result_id,
                'title': (titles.get(result_id) or DELETED_SUMMARY) if kind == AIUsageKind.SUMMARY else None,
                'models': list(dict.fromkeys(row['model'] for row in group)),
            }
            for (kind, result_id), group in sorted(groups.items(), key=lambda item: KIND_ORDER.index(item[0][0]))
        ]
        return {'lines': lines, 'total': _totals(rows)}

    @staticmethod
    async def organization(organization_id: UUID, since: Any, until: Any) -> dict[str, Any]:
        """Spending per user in [since, until): their recordings' automatic processing and their own summaries."""
        rows = await AIUsage.filter(
            organization_id=organization_id, created_at__gte=since, created_at__lt=until
        ).values(*USAGE_FIELDS)
        by_user: dict[UUID | None, list[dict[str, Any]]] = {}
        for row in rows:
            by_user.setdefault(row['user_id'], []).append(row)
        users = {user.id: user for user in await User.filter(id__in=[key for key in by_user if key])}

        def summary(user_id: UUID | None, name: str, group: list[dict[str, Any]]) -> dict[str, Any]:
            def kinds(*wanted: AIUsageKind) -> list[dict[str, Any]]:
                return [row for row in group if row['kind'] in wanted]

            return {
                **_totals(group),
                'user_id': user_id,
                'name': name,
                'recordings': len({row['recording_id'] for row in group if row['recording_id']}),
                'transcription_cost_usd': _cost_sum(kinds(AIUsageKind.TRANSCRIPTION)),
                'summary_cost_usd': _cost_sum(kinds(AIUsageKind.SUMMARY)),
                'other_cost_usd': _cost_sum(kinds(AIUsageKind.TITLE, AIUsageKind.TAGS, AIUsageKind.SPEAKERS)),
            }

        def display(user_id: UUID | None) -> str:
            user = users.get(user_id) if user_id else None
            if user is None:
                return DELETED_USER
            return ' '.join(part for part in (user.first_name, user.last_name) if part).strip() or user.email

        lines = [summary(user_id, display(user_id), group) for user_id, group in by_user.items()]
        lines.sort(key=lambda line: (-line['cost_usd'], line['name']))
        first = await AIUsage.filter(organization_id=organization_id).order_by('created_at').first()
        return {
            'since': since,
            'until': until,
            'users': lines,
            'total': summary(None, 'Итого', rows),
            'accounting_since': first.created_at if first else None,
        }
