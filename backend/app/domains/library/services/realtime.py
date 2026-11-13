from datetime import datetime
from uuid import UUID

from loguru import logger
from tortoise.queryset import QuerySet

from app.core.utils.date_utils import utcnow
from app.domains.library.models import Recording
from app.domains.organization.services.organization_websocket_service import OrganizationWebSocketService

RECORDING_UPDATED = 'recording.updated'
RECORDING_DELETED = 'recording.deleted'
# Many recordings changed at once (project made private, tag merged): clients run /recordings/sync
RECORDINGS_RESYNC = 'recordings.resync'
# Above this many recordings a bulk change sends one RECORDINGS_RESYNC instead of one event per recording
TOUCH_EVENT_LIMIT = 50


class LibraryRealtime:
    """
    Recording events on the organization channel. Payloads carry only `{id, updated_at}`: every member of the
    organization receives them, and clients refetch through the visibility-checked API (detail or sync).
    """

    @staticmethod
    async def _send(organization_id: UUID, message_type: str, data: dict) -> None:
        try:
            await OrganizationWebSocketService.notify(organization_id, message_type, data)
        except Exception as e:
            # Realtime is best effort: clients also poll /recordings/sync.
            logger.warning('Could not publish {} to organization {}: {}', message_type, organization_id, e)

    @classmethod
    async def recording_updated(cls, recording: Recording) -> None:
        await cls._send(
            recording.organization_id, RECORDING_UPDATED, {'id': recording.id, 'updated_at': recording.updated_at}
        )

    @classmethod
    async def recording_deleted(cls, recording: Recording) -> None:
        await cls._send(
            recording.organization_id, RECORDING_DELETED, {'id': recording.id, 'updated_at': recording.updated_at}
        )

    @classmethod
    async def _notify_many(cls, rows: list[tuple[UUID, UUID, datetime]], message_type: str) -> None:
        """One event per recording, or one RECORDINGS_RESYNC per organization above TOUCH_EVENT_LIMIT."""
        if len(rows) > TOUCH_EVENT_LIMIT:
            latest: dict[UUID, datetime] = {}
            for _, organization_id, updated_at in rows:
                latest[organization_id] = max(latest.get(organization_id, updated_at), updated_at)
            for organization_id, updated_at in latest.items():
                await cls._send(organization_id, RECORDINGS_RESYNC, {'updated_at': updated_at})
            return
        for recording_id, organization_id, updated_at in rows:
            await cls._send(organization_id, message_type, {'id': recording_id, 'updated_at': updated_at})

    @classmethod
    async def recordings_changed(cls, recordings: list[Recording], *, deleted: bool = False) -> None:
        """Saved recordings of a bulk action: `recording.updated` / `recording.deleted` each, or one resync."""
        rows = [(recording.id, recording.organization_id, recording.updated_at) for recording in recordings]
        await cls._notify_many(rows, RECORDING_DELETED if deleted else RECORDING_UPDATED)

    @classmethod
    async def touch(cls, recordings: QuerySet[Recording]) -> int:
        """
        Bump `updated_at` of recordings whose visibility or nested data changed without saving them (project made
        private, member removed, tag renamed or merged), so /recordings/sync picks them up, and notify.
        """
        rows: list[tuple[UUID, UUID]] = await recordings.values_list('id', 'organization_id')
        ids = [row[0] for row in rows]
        if not ids:
            return 0
        now = utcnow()
        await Recording.filter(id__in=ids).update(updated_at=now)
        await cls._notify_many(
            [(recording_id, organization_id, now) for recording_id, organization_id in rows], RECORDING_UPDATED
        )
        return len(ids)
