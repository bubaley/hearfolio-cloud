import base64
import binascii
import json
import re
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from tortoise.contrib.postgres.search import SearchHeadline, SearchQuery
from tortoise.expressions import Q, Subquery
from tortoise.queryset import QuerySet

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.domains.library.models import Recording, RecordingVisibility
from app.domains.library.schemas import (
    RecordingDetailSchema,
    RecordingListQuery,
    RecordingReadSchema,
    RecordingSyncSchema,
    SnippetPartSchema,
)
from app.domains.library.services.visibility import LibraryVisibility
from app.domains.user.models import User

SEARCH_CONFIG = 'simple'
# Private-use characters mark matches inside ts_headline output; they never occur in transcripts.
HIGHLIGHT_START = ''
HIGHLIGHT_STOP = ''
SNIPPET_RADIUS = 80
SYNC_PAGE_SIZE = 100


def _is_postgres(queryset: QuerySet) -> bool:
    return queryset.model._meta.db.capabilities.dialect == 'postgres'


class RecordingQueryService:
    """Listing, full-text search and sync; every query starts from LibraryVisibility.recordings."""

    # LIST AND SEARCH

    @staticmethod
    def filter(queryset: QuerySet[Recording], query: RecordingListQuery, user: User) -> QuerySet[Recording]:
        if query.project_id is not None:
            queryset = queryset.filter(project_id=query.project_id)
        if query.tag_id is not None:
            queryset = queryset.filter(id__in=Subquery(Recording.filter(tags__id=query.tag_id).values('id')))
        if query.created_by_id is not None:
            queryset = queryset.filter(created_by_id=query.created_by_id)
        if query.status is not None:
            queryset = queryset.filter(status=query.status)
        if query.personal is True:
            queryset = queryset.filter(visibility=RecordingVisibility.PERSONAL, created_by_id=user.id)
        elif query.personal is False:
            queryset = queryset.filter(visibility=RecordingVisibility.ORGANIZATION)
        if query.recorded_from is not None:
            queryset = queryset.filter(recorded_at__gte=datetime.combine(query.recorded_from, time.min, tzinfo=UTC))
        if query.recorded_to is not None:
            end = datetime.combine(query.recorded_to, time.min, tzinfo=UTC) + timedelta(days=1)
            queryset = queryset.filter(recorded_at__lt=end)
        return queryset

    @staticmethod
    def search_text(query: RecordingListQuery) -> str | None:
        text = ' '.join((query.search or '').split())
        return text or None

    @staticmethod
    def search(queryset: QuerySet[Recording], text: str) -> QuerySet[Recording]:
        """PostgreSQL: `simple` full-text match on the generated, GIN-indexed `search_vector`. SQLite: ILIKE."""
        if _is_postgres(queryset):
            return queryset.filter(search_vector__search=SearchQuery(text, config=SEARCH_CONFIG)).annotate(
                search_headline=SearchHeadline(
                    'transcript_text',
                    SearchQuery(text, config=SEARCH_CONFIG),
                    config=SEARCH_CONFIG,
                    start_sel=HIGHLIGHT_START,
                    stop_sel=HIGHLIGHT_STOP,
                    max_words=30,
                    min_words=12,
                    max_fragments=1,
                )
            )
        return queryset.filter(Q(title__icontains=text) | Q(transcript_text__icontains=text))

    @classmethod
    def snippet(cls, recording: Recording, text: str) -> list[SnippetPartSchema] | None:
        headline = getattr(recording, 'search_headline', None)
        if headline is not None:
            if HIGHLIGHT_START not in headline:
                return None
            return cls._parse_headline(headline)
        return cls._plain_snippet(recording.transcript_text, text)

    @staticmethod
    def _parse_headline(headline: str) -> list[SnippetPartSchema]:
        parts: list[SnippetPartSchema] = []
        for chunk in re.split(f'({HIGHLIGHT_START}.*?{HIGHLIGHT_STOP})', headline):
            if not chunk:
                continue
            highlighted = chunk.startswith(HIGHLIGHT_START)
            parts.append(SnippetPartSchema(text=chunk.strip(HIGHLIGHT_START + HIGHLIGHT_STOP), highlight=highlighted))
        return parts

    @staticmethod
    def _plain_snippet(transcript: str, text: str) -> list[SnippetPartSchema] | None:
        index = transcript.casefold().find(text.casefold())
        if index < 0:
            return None
        start = max(0, index - SNIPPET_RADIUS)
        end = min(len(transcript), index + len(text) + SNIPPET_RADIUS)
        parts = [
            SnippetPartSchema(text=transcript[start:index], highlight=False),
            SnippetPartSchema(text=transcript[index : index + len(text)], highlight=True),
            SnippetPartSchema(text=transcript[index + len(text) : end], highlight=False),
        ]
        return [part for part in parts if part.text]

    @classmethod
    async def serialize(cls, recordings: list[Recording], search_text: str | None = None) -> list[RecordingReadSchema]:
        if not recordings:
            return []
        await Recording.fetch_for_list(recordings, 'created_by', 'project', 'suggested_project', 'tags')
        items = [RecordingReadSchema.model_validate(recording) for recording in recordings]
        if search_text:
            for item, recording in zip(items, recordings, strict=True):
                item.snippet = cls.snippet(recording, search_text)
        return items

    # SYNC

    @staticmethod
    def encode_cursor(updated_at: datetime, recording_id: UUID) -> str:
        raw = json.dumps({'u': updated_at.isoformat(), 'i': str(recording_id)}).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')

    @staticmethod
    def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            raw = base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4))
            data = json.loads(raw)
            return datetime.fromisoformat(data['u']), UUID(data['i'])
        except (binascii.Error, ValueError, KeyError, TypeError) as e:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Invalid cursor') from e

    @classmethod
    async def sync(
        cls, user: User, organization_id: UUID, cursor: str | None, limit: int = SYNC_PAGE_SIZE
    ) -> RecordingSyncSchema:
        """
        Pages over every recording of the organization changed after the cursor, ordered by (updated_at, id).
        A visible one becomes an item; anything else (deleted, made personal, moved to a private project) only
        contributes its id to `deleted_ids`, so the client drops it if it has it.
        """
        stream = Recording.filter(LibraryVisibility.member_of_organization(user, organization_id)).filter(
            organization_id=organization_id
        )
        if cursor:
            updated_at, last_id = cls.decode_cursor(cursor)
            stream = stream.filter(Q(updated_at__gt=updated_at) | Q(updated_at=updated_at, id__gt=last_id))
        rows: list[tuple[UUID, datetime]] = (
            await stream.order_by('updated_at', 'id').limit(limit + 1).values_list('id', 'updated_at')
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        ids = [row[0] for row in rows]
        visible = {
            recording.id: recording
            for recording in await LibraryVisibility.recordings(user, organization_id).filter(id__in=ids)
        }
        ordered = [visible[recording_id] for recording_id in ids if recording_id in visible]
        if ordered:
            await Recording.fetch_for_list(ordered, 'created_by', 'project', 'suggested_project', 'tags')
        return RecordingSyncSchema(
            items=[RecordingDetailSchema.model_validate(recording) for recording in ordered],
            deleted_ids=[recording_id for recording_id in ids if recording_id not in visible],
            next_cursor=cls.encode_cursor(rows[-1][1], rows[-1][0]) if rows else cursor,
            has_more=has_more,
        )
