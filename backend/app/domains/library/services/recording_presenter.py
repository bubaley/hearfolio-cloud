from typing import cast
from uuid import UUID

from app.domains.library.models import ProjectSuggestionState, Recording
from app.domains.library.schemas import RecordingDetailSchema, RecordingReadSchema
from app.domains.library.services.visibility import LibraryVisibility
from app.domains.user.models import User

RECORDING_RELATIONS = ('created_by', 'project', 'suggested_project', 'tags')


class RecordingPresenter:
    """
    The only way recordings leave the API (list, detail, sync, search, write responses). Project references are
    shown per viewer: a project the viewer cannot see (a private one they are not a member of) is never named.

    - `suggested_project`: an invisible suggestion becomes null with `project_suggestion_state = none`.
    - `project`: the author still sees their own recording in a private project they left; it shows as having no
      project (`project_id` and `project` null), so its name does not leak.
    """

    @staticmethod
    async def _visible_project_ids(recordings: list[Recording], viewer: User) -> set[UUID]:
        referenced: dict[UUID, set[UUID]] = {}
        for recording in recordings:
            ids = {pid for pid in (recording.project_id, recording.suggested_project_id) if pid is not None}
            if ids:
                referenced.setdefault(recording.organization_id, set()).update(ids)
        visible: set[UUID] = set()
        for organization_id, project_ids in referenced.items():
            rows = await (
                LibraryVisibility.projects(viewer, organization_id)
                .filter(id__in=list(project_ids))
                .values_list('id', flat=True)
            )
            visible.update(cast(list[UUID], rows))
        return visible

    @staticmethod
    def _redact[SchemaT: RecordingReadSchema](item: SchemaT, visible: set[UUID]) -> SchemaT:
        if item.suggested_project_id is not None and item.suggested_project_id not in visible:
            item.suggested_project_id = None
            item.suggested_project = None
            item.project_suggestion_state = ProjectSuggestionState.NONE
        if item.project_id is not None and item.project_id not in visible:
            item.project_id = None
            item.project = None
        return item

    @classmethod
    async def many[SchemaT: RecordingReadSchema](
        cls, recordings: list[Recording], viewer: User, schema: type[SchemaT]
    ) -> list[SchemaT]:
        if not recordings:
            return []
        await Recording.fetch_for_list(recordings, *RECORDING_RELATIONS)
        visible = await cls._visible_project_ids(recordings, viewer)
        return [cls._redact(schema.model_validate(recording), visible) for recording in recordings]

    @classmethod
    async def detail(cls, recording: Recording, viewer: User) -> RecordingDetailSchema:
        return (await cls.many([recording], viewer, RecordingDetailSchema))[0]
