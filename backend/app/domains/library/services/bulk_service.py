from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict
from tortoise.queryset import QuerySet
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.utils.date_utils import utcnow
from app.domains.library.models import Project, Recording, RecordingEvent, RecordingEventKind, Tag
from app.domains.library.schemas import (
    RecordingBulkAction,
    RecordingBulkResultSchema,
    RecordingBulkSchema,
    RecordingBulkSkippedSchema,
    RecordingBulkSkipReason,
)
from app.domains.library.services.realtime import LibraryRealtime
from app.domains.library.services.recording_service import RecordingService
from app.domains.organization.services.organization_service import OrganizationService
from app.domains.user.models import User


class RecordingBulkData(BaseModel):
    """A validated bulk request: the recordings the action may touch, in request order, and what was skipped."""

    action: RecordingBulkAction
    actor: User
    recordings: list[Recording]
    skipped: list[RecordingBulkSkippedSchema]
    project: Project | None = None
    add_tags: list[Tag] = []
    remove_tags: list[Tag] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)


class RecordingBulkService:
    """
    `POST /recordings/bulk`: one action over many recordings with the rules of the single endpoints. Ids the caller
    cannot see (or that are not in the state the action needs) are skipped as `not_found`, ids it may not change as
    `forbidden`; everything else is applied in one transaction, journaled per recording, then announced (one
    `recordings.resync` above 50 recordings, see LibraryRealtime).
    """

    @classmethod
    async def validate(
        cls, data: RecordingBulkSchema, actor: User, organization_id: UUID, visible: QuerySet[Recording]
    ) -> RecordingBulkData:
        """`visible`: the caller's recordings in the state the action needs (deleted ones for `restore`)."""
        project: Project | None = None
        add_tags: list[Tag] = []
        remove_tags: list[Tag] = []
        if data.action == RecordingBulkAction.MOVE and data.project_id is not None:
            project = await RecordingService.validate_project(data.project_id, organization_id, actor)
        if data.action == RecordingBulkAction.TAGS:
            if not data.add_tag_ids and not data.remove_tag_ids:
                raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Nothing to change')
            if set(data.add_tag_ids) & set(data.remove_tag_ids):
                raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'A tag cannot be added and removed at once')
            add_tags = await RecordingService.validate_tags(data.add_tag_ids, organization_id)
            remove_tags = await RecordingService.validate_tags(data.remove_tag_ids, organization_id)

        ids = list(dict.fromkeys(data.ids))
        found = {recording.id: recording for recording in await visible.filter(id__in=ids)}
        needs_owner = data.action in (RecordingBulkAction.DELETE, RecordingBulkAction.RESTORE)
        is_admin = needs_owner and await OrganizationService.is_admin(actor, organization_id)
        recordings: list[Recording] = []
        skipped: list[RecordingBulkSkippedSchema] = []
        for recording_id in ids:
            recording = found.get(recording_id)
            if recording is None:
                skipped.append(RecordingBulkSkippedSchema(id=recording_id, reason=RecordingBulkSkipReason.NOT_FOUND))
            elif needs_owner and not is_admin and recording.created_by_id != actor.id:
                skipped.append(RecordingBulkSkippedSchema(id=recording_id, reason=RecordingBulkSkipReason.FORBIDDEN))
            else:
                recordings.append(recording)
        return RecordingBulkData(
            action=data.action,
            actor=actor,
            recordings=recordings,
            skipped=skipped,
            project=project,
            add_tags=add_tags,
            remove_tags=remove_tags,
        )

    @classmethod
    async def apply(cls, data: RecordingBulkData) -> RecordingBulkResultSchema:
        changed: list[Recording] = []
        events: list[RecordingEvent] = []

        def journal(recording: Recording, kind: RecordingEventKind, event_data: dict[str, Any] | None = None) -> None:
            events.append(
                RecordingEvent(
                    recording_id=recording.id,
                    actor_id=data.actor.id,
                    kind=kind,
                    data=jsonable_encoder(event_data or {}),
                )
            )

        if data.action == RecordingBulkAction.TAGS and data.recordings:
            await Recording.fetch_for_list(data.recordings, 'tags')

        async with in_transaction():
            now = utcnow()
            for recording in data.recordings:
                fields: list[str] = []
                if data.action == RecordingBulkAction.MOVE:
                    if move := RecordingService.apply_move(recording, data.project):
                        fields = move[0]
                        journal(recording, RecordingEventKind.MOVED, move[1])
                elif data.action == RecordingBulkAction.TAGS:
                    if tag_event := await cls._change_tags(recording, data.add_tags, data.remove_tags):
                        journal(recording, RecordingEventKind.TAGGED, tag_event)
                        recording.updated_at = now
                        await Recording.filter(id=recording.id).update(updated_at=now)
                        changed.append(recording)
                    continue
                elif data.action == RecordingBulkAction.DELETE:
                    recording.deleted_at = now
                    fields = ['deleted_at']
                    journal(recording, RecordingEventKind.DELETED)
                elif data.action == RecordingBulkAction.RESTORE:
                    recording.deleted_at = None
                    fields = ['deleted_at']
                    journal(recording, RecordingEventKind.RESTORED)
                if fields:
                    recording.updated_at = now
                    await recording.save(update_fields=[*fields, 'updated_at'])
                    changed.append(recording)
            if events:
                await RecordingEvent.bulk_create(events)

        await LibraryRealtime.recordings_changed(changed, deleted=data.action == RecordingBulkAction.DELETE)
        return RecordingBulkResultSchema(updated=[recording.id for recording in data.recordings], skipped=data.skipped)

    @staticmethod
    async def _change_tags(recording: Recording, add: list[Tag], remove: list[Tag]) -> dict[str, Any] | None:
        current = {tag.id for tag in recording.tags}
        added = [tag for tag in add if tag.id not in current]
        removed = [tag for tag in remove if tag.id in current]
        if removed:
            await recording.tags.remove(*removed)
        if added:
            await recording.tags.add(*added)
        if not added and not removed:
            return None
        return {'added': [tag.name for tag in added], 'removed': [tag.name for tag in removed]}
