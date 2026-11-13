from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_ronin.decorators import action, viewset

from app.core.auth import get_current_auth_state
from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.viewsets import BaseModelViewSet, LightPageNumberPagination, PageResponse, with_stable_ordering
from app.domains.library.filters import ProjectFilterSet, TagFilterSet
from app.domains.library.models import Project, ProjectMember, Recording, RecordingEvent, Tag
from app.domains.library.schemas import (
    AudioUrlSchema,
    ProjectCreateSchema,
    ProjectMemberCreateSchema,
    ProjectMemberReadSchema,
    ProjectReadSchema,
    ProjectUpdateSchema,
    PublicShareSchema,
    RecordingCreatedSchema,
    RecordingCreateSchema,
    RecordingDetailSchema,
    RecordingEventReadSchema,
    RecordingListQuery,
    RecordingReadSchema,
    RecordingSyncSchema,
    RecordingUpdateSchema,
    ShareLinkReadSchema,
    ShareLinkUpsertSchema,
    TagCreateSchema,
    TagMergeSchema,
    TagReadSchema,
    TagUpdateSchema,
    TagUsageSchema,
    UploadCompleteSchema,
    UploadPartsRequestSchema,
    UploadPlanSchema,
)
from app.domains.library.services.project_service import ProjectService
from app.domains.library.services.recording_presenter import RecordingPresenter
from app.domains.library.services.recording_query import SYNC_PAGE_SIZE, RecordingQueryService
from app.domains.library.services.recording_service import RecordingService
from app.domains.library.services.share_link_service import ShareLinkService
from app.domains.library.services.tag_service import TagService
from app.domains.library.services.upload_service import UploadService
from app.domains.library.services.visibility import LibraryVisibility
from app.shared.services.filter_objects_manager import FilterObjectsManager

projects_router = APIRouter(prefix='/projects', tags=['projects'])
tags_router = APIRouter(prefix='/tags', tags=['tags'])
recordings_router = APIRouter(prefix='/recordings', tags=['recordings'])
public_share_router = APIRouter(prefix='/public/share', tags=['public-share'])
routers = (projects_router, tags_router, recordings_router, public_share_router)


def _organization_id() -> UUID:
    organization_id = get_current_auth_state().organization_id
    if organization_id is None:
        raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Organization-Key header is required')
    return organization_id


@viewset(projects_router)
class ProjectViewSet(BaseModelViewSet[Project]):
    """`GET /projects` lists the projects the caller can see and file into; `/projects/manage` adds, for org admins,
    every private project (settings). Other routes work on the manageable set."""

    model = Project
    read_schema = ProjectReadSchema
    create_schema = ProjectCreateSchema
    update_schema = ProjectUpdateSchema
    filterset_class = ProjectFilterSet

    async def get_queryset(self):
        organization_id = _organization_id()
        if self.action == 'list':
            queryset = LibraryVisibility.projects(self.user, organization_id)
        else:
            queryset = await ProjectService.manageable(self.user, organization_id)
        return FilterObjectsManager.filter(queryset, get_current_auth_state())

    async def perform_create(self, obj: Project) -> Project:
        return await ProjectService.create(obj, self.user)

    async def perform_destroy(self, obj: Project) -> None:
        await ProjectService.delete(obj, self.user)

    @action(methods=['GET'], detail=False)
    async def manage(self) -> list[ProjectReadSchema]:
        """Every project the caller may manage: visible ones, plus all private ones for org admins."""
        return await ProjectReadSchema.from_queryset(await self.get_queryset())

    @action(methods=['PUT', 'PATCH'], detail=True)
    async def update(self, item_id: UUID, data: ProjectUpdateSchema) -> ProjectReadSchema:
        project = await self.get_object(item_id)
        project = await ProjectService.update(project, data.model_dump(exclude_unset=True), self.user)
        return await ProjectReadSchema.from_tortoise_orm(project)

    @action(methods=['GET'], detail=True)
    async def members(self, item_id: UUID) -> list[ProjectMemberReadSchema]:
        project = await self.get_object(item_id)
        return await ProjectMemberReadSchema.from_queryset(ProjectMember.filter(project_id=project.id))

    @action(methods=['POST'], detail=True, path='members', status_code=201)
    async def add_member(self, item_id: UUID, data: ProjectMemberCreateSchema) -> ProjectMemberReadSchema:
        project = await self.get_object(item_id)
        member = await ProjectService.add_member(project, data.user_id, self.user)
        return await ProjectMemberReadSchema.from_tortoise_orm(member)

    @action(methods=['DELETE'], detail=True, path='members/{member}', status_code=204)
    async def remove_member(self, item_id: UUID, member: UUID) -> None:
        """`member` is the user id."""
        project = await self.get_object(item_id)
        membership = await ProjectMember.get_or_none(project_id=project.id, user_id=member)
        if membership is None:
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, 'Not a member of this project')
        await ProjectService.remove_member(project, membership, self.user)


@viewset(tags_router)
class TagViewSet(BaseModelViewSet[Tag]):
    model = Tag
    read_schema = TagReadSchema
    create_schema = TagCreateSchema
    update_schema = TagUpdateSchema
    filterset_class = TagFilterSet

    async def perform_create(self, obj: Tag) -> Tag:
        return await TagService.create(obj)

    async def perform_update(self, obj: Tag) -> Tag:
        return await TagService.update(obj, self.user)

    async def perform_destroy(self, obj: Tag) -> None:
        await TagService.delete(obj, self.user)

    @action(methods=['GET'], detail=False)
    async def usage(self) -> list[TagUsageSchema]:
        """Recordings per tag, counting only recordings the caller can see; unused tags are left out."""
        counts = await TagService.usage(self.user, _organization_id())
        return [TagUsageSchema(tag_id=tag_id, recordings_count=count) for tag_id, count in counts.items()]

    @action(methods=['POST'], detail=True)
    async def merge(self, item_id: UUID, data: TagMergeSchema) -> TagReadSchema:
        """Move every recording of this tag to `target_id` and delete this tag. Org admins only."""
        source = await self.get_object(item_id)
        target = await self.get_object(data.target_id)
        return await TagReadSchema.from_tortoise_orm(await TagService.merge(source, target, self.user))


RecordingPage = PageResponse[RecordingReadSchema, LightPageNumberPagination]


@viewset(recordings_router)
class RecordingViewSet(BaseModelViewSet[Recording]):
    """Every route starts from LibraryVisibility.recordings: what the caller cannot see is a 404."""

    model = Recording
    read_schema = RecordingDetailSchema
    create_schema = RecordingCreateSchema
    update_schema = RecordingUpdateSchema

    async def get_queryset(self):
        return self.visible()

    def visible(self, *, deleted: bool | None = False):
        queryset = LibraryVisibility.recordings(self.user, _organization_id(), deleted=deleted)
        return FilterObjectsManager.filter(queryset, get_current_auth_state())

    async def get_deleted_object(self, item_id: UUID) -> Recording:
        recording = await self.visible(deleted=True).get_or_none(id=item_id)
        if recording is None:
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, 'Not found')
        return recording

    @action(methods=['GET'], detail=False, name='list')
    async def list_recordings(
        self,
        query: Annotated[RecordingListQuery, Query()],
        pagination: Annotated[LightPageNumberPagination, Depends(LightPageNumberPagination.build)],
    ) -> RecordingPage:
        """Newest first. `search` matches title and transcript; each match carries a highlighted `snippet`."""
        queryset = RecordingQueryService.filter(self.visible(deleted=query.deleted), query, self.user)
        search_text = RecordingQueryService.search_text(query)
        if search_text:
            queryset = RecordingQueryService.search(queryset, search_text)
        page = await pagination.paginate(with_stable_ordering(queryset))
        items = await RecordingQueryService.serialize(page, self.user, search_text)
        await pagination.fill_meta(queryset=queryset, data=items)
        return cast(RecordingPage, RecordingPage.wrap(data=items, pagination=pagination))

    @action(methods=['POST'], detail=False, status_code=201)
    async def create(self, data: RecordingCreateSchema) -> RecordingCreatedSchema:
        """Create (or, for a known `client_id`, return) a recording with an upload plan for its audio."""
        organization = get_current_auth_state().organization
        if organization is None:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Organization-Key header is required')
        recording = await UploadService.find_existing(organization, data.client_id)
        if recording is not None:
            UploadService.validate_existing(recording, self.user)
        else:
            payload = await UploadService.validate_create(organization, self.user, data)
            recording = await UploadService.create(payload)
        return RecordingCreatedSchema(
            recording=await RecordingPresenter.detail(recording, self.user),
            upload=await UploadService.plan(recording),
        )

    @action(methods=['GET'], detail=True, name='retrieve')
    async def retrieve(self, item_id: UUID) -> RecordingDetailSchema:
        return await RecordingPresenter.detail(await self.get_object(item_id), self.user)

    @action(methods=['GET'], detail=False)
    async def sync(
        self,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = SYNC_PAGE_SIZE,
    ) -> RecordingSyncSchema:
        """Changes since `cursor` (omit for everything), with tombstones in `deleted_ids`."""
        return await RecordingQueryService.sync(self.user, _organization_id(), cursor, limit)

    @action(methods=['PUT', 'PATCH'], detail=True)
    async def update(self, item_id: UUID, data: RecordingUpdateSchema) -> RecordingDetailSchema:
        recording = await self.get_object(item_id)
        changes = await RecordingService.validate_update(recording, data, self.user)
        recording = await RecordingService.update(recording, changes, self.user)
        return await RecordingPresenter.detail(recording, self.user)

    async def perform_destroy(self, obj: Recording) -> None:
        await RecordingService.delete(obj, self.user)

    @action(methods=['POST'], detail=True)
    async def restore(self, item_id: UUID) -> RecordingDetailSchema:
        recording = await RecordingService.restore(await self.get_deleted_object(item_id), self.user)
        return await RecordingPresenter.detail(recording, self.user)

    @action(methods=['GET'], detail=True)
    async def audio(self, item_id: UUID, download: bool = False) -> AudioUrlSchema:
        """Presigned GET for streaming or caching; `download=true` asks the browser to save it."""
        return await RecordingService.audio_url(await self.get_object(item_id), download=download)

    @action(methods=['POST'], detail=True, path='upload/parts')
    async def upload_parts(self, item_id: UUID, data: UploadPartsRequestSchema) -> UploadPlanSchema:
        """Fresh upload URLs (resume after a restart or expiry). Author only."""
        return await UploadService.refresh_plan(await self.get_object(item_id), self.user, data.part_numbers)

    @action(methods=['POST'], detail=True, path='upload/complete')
    async def upload_complete(self, item_id: UUID, data: UploadCompleteSchema) -> RecordingDetailSchema:
        """Verify the uploaded object and start processing. Author only; repeating it is harmless."""
        recording = await UploadService.complete(await self.get_object(item_id), self.user, data)
        return await RecordingPresenter.detail(recording, self.user)

    @action(methods=['POST'], detail=True, path='project-suggestion/accept')
    async def accept_project_suggestion(self, item_id: UUID) -> RecordingDetailSchema:
        recording = await self.get_object(item_id)
        recording = await RecordingService.resolve_project_suggestion(recording, True, self.user)
        return await RecordingPresenter.detail(recording, self.user)

    @action(methods=['POST'], detail=True, path='project-suggestion/dismiss')
    async def dismiss_project_suggestion(self, item_id: UUID) -> RecordingDetailSchema:
        recording = await self.get_object(item_id)
        recording = await RecordingService.resolve_project_suggestion(recording, False, self.user)
        return await RecordingPresenter.detail(recording, self.user)

    @action(methods=['GET'], detail=True)
    async def events(self, item_id: UUID) -> list[RecordingEventReadSchema]:
        """The «История» journal, newest first."""
        recording = await self.get_object(item_id)
        return await RecordingEventReadSchema.from_queryset(RecordingEvent.filter(recording_id=recording.id))

    @action(methods=['GET'], detail=True)
    async def share(self, item_id: UUID) -> ShareLinkReadSchema | None:
        """The active public link, or null."""
        link = await ShareLinkService.active(await self.get_object(item_id))
        return await ShareLinkReadSchema.from_tortoise_orm(link) if link else None

    @action(methods=['PUT'], detail=True, path='share')
    async def update_share(self, item_id: UUID, data: ShareLinkUpsertSchema) -> ShareLinkReadSchema:
        """Create the public link or change what it exposes (the token stays)."""
        link = await ShareLinkService.upsert(await self.get_object(item_id), data, self.user)
        return await ShareLinkReadSchema.from_tortoise_orm(link)

    @action(methods=['DELETE'], detail=True, path='share', status_code=204)
    async def revoke_share(self, item_id: UUID) -> None:
        await ShareLinkService.revoke(await self.get_object(item_id), self.user)


@public_share_router.get('/{token}', name='retrieve')
async def retrieve_public_share(token: str) -> PublicShareSchema:
    """Public, no auth: exactly what the link exposes. 404 when the link is unknown, revoked or expired."""
    return await ShareLinkService.open_public(await ShareLinkService.get_public(token))
