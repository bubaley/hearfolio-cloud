from typing import Any

from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.queryset import QuerySet
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.utils.date_utils import utcnow
from app.domains.library.models import Project, ProjectMember, Recording
from app.domains.library.services.realtime import LibraryRealtime
from app.domains.library.services.visibility import LibraryVisibility
from app.domains.organization.models import OrganizationUser
from app.domains.organization.services.organization_service import OrganizationService
from app.domains.user.models import User


class ProjectService:
    """
    Public projects: any member creates and edits them. Private projects: created by any member (who becomes a
    member), edited and staffed by their members and org admins. Making a project private or public, and
    deleting it, is for org admins and the project's creator.
    """

    @staticmethod
    async def manageable(user: User, organization_id: Any) -> QuerySet[Project]:
        """Projects the user may open in settings: visible ones, plus every private one for org admins."""
        if await OrganizationService.is_admin(user, organization_id):
            return Project.filter(organization_id=organization_id)
        return LibraryVisibility.projects(user, organization_id)

    @staticmethod
    def referencing(project: Project) -> QuerySet[Recording]:
        """Recordings filed into or suggested for the project: their serialized form depends on who sees it."""
        return Recording.filter(Q(project_id=project.id) | Q(suggested_project_id=project.id))

    @staticmethod
    async def is_member(project: Project, user: User) -> bool:
        return await ProjectMember.exists(project_id=project.id, user_id=user.id)

    @classmethod
    async def can_edit(cls, project: Project, user: User) -> bool:
        if not project.is_private:
            return True
        return await cls.is_member(project, user) or await OrganizationService.is_admin(user, project.organization_id)

    @staticmethod
    async def can_change_privacy(project: Project, user: User) -> bool:
        return project.created_by_id == user.id or await OrganizationService.is_admin(user, project.organization_id)

    @classmethod
    async def create(cls, project: Project, actor: User) -> Project:
        project.created_by_id = actor.id
        async with in_transaction():
            await project.save()
            if project.is_private:
                await ProjectMember.create(project_id=project.id, user_id=actor.id)
        return project

    @classmethod
    async def update(cls, project: Project, changes: dict[str, Any], actor: User) -> Project:
        if not await cls.can_edit(project, actor):
            raise AppException.from_attrs(ErrorCode.FORBIDDEN, 'Only project members can edit a private project')
        privacy_changed = 'is_private' in changes and changes['is_private'] != project.is_private
        if privacy_changed and not await cls.can_change_privacy(project, actor):
            raise AppException.from_attrs(
                ErrorCode.FORBIDDEN, 'Only the creator or an organization admin can change project access'
            )
        for field in ('name', 'emoji', 'description', 'is_private'):
            if field in changes and (field == 'emoji' or changes[field] is not None):
                setattr(project, field, changes[field])
        if changes.get('archived') is not None:
            project.archived_at = (project.archived_at or utcnow()) if changes['archived'] else None
        async with in_transaction():
            await project.save()
            if privacy_changed and project.is_private:
                await ProjectMember.get_or_create(project_id=project.id, user_id=actor.id)
        # Names are nested in recordings; access changes alter who sees them.
        await LibraryRealtime.touch(cls.referencing(project))
        return project

    @classmethod
    async def delete(cls, project: Project, actor: User) -> None:
        if not await cls.can_change_privacy(project, actor):
            raise AppException.from_attrs(
                ErrorCode.FORBIDDEN, 'Only the creator or an organization admin can delete a project'
            )
        recording_ids = await cls.referencing(project).values_list('id', flat=True)
        await project.delete()
        await LibraryRealtime.touch(Recording.filter(id__in=recording_ids))

    # MEMBERS

    @classmethod
    async def validate_members_change(cls, project: Project, actor: User) -> None:
        if not project.is_private:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Only private projects have members')
        if not await cls.can_edit(project, actor):
            raise AppException.from_attrs(ErrorCode.FORBIDDEN, 'Only project members and admins manage members')

    @classmethod
    async def add_member(cls, project: Project, user_id: Any, actor: User) -> ProjectMember:
        await cls.validate_members_change(project, actor)
        if not await OrganizationUser.exists(organization_id=project.organization_id, user_id=user_id):
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'User is not a member of this organization')
        try:
            member = await ProjectMember.create(project_id=project.id, user_id=user_id)
        except IntegrityError:
            raise AppException.from_attrs(ErrorCode.CONFLICT, 'User is already a member of this project')
        await LibraryRealtime.touch(cls.referencing(project))
        return member

    @classmethod
    async def remove_member(cls, project: Project, member: ProjectMember, actor: User) -> None:
        await cls.validate_members_change(project, actor)
        await member.delete()
        await LibraryRealtime.touch(cls.referencing(project))
