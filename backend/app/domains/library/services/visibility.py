from uuid import UUID

from tortoise.expressions import Q, Subquery
from tortoise.queryset import QuerySet

from app.domains.library.models import Project, ProjectMember, Recording, RecordingVisibility
from app.domains.organization.models import OrganizationUser
from app.domains.user.models import User


class LibraryVisibility:
    """
    The single source of "who sees what" in the library. Every endpoint that reads projects or recordings
    (list, detail, sync, search, audio, share management, events) starts from these querysets.

    A recording is visible when it is in one of the user's organizations, not deleted, and the user is its
    author, or it is shared with the organization and its project is absent, public, or has the user as a
    member. Org admins get no extra recordings: private projects behave like Notion teamspaces.
    """

    @staticmethod
    def member_of_organization(user: User, organization_id: UUID) -> Q:
        member_org_ids = OrganizationUser.filter(user_id=user.id, organization_id=organization_id).values(
            'organization_id'
        )
        return Q(organization_id__in=Subquery(member_org_ids))

    @staticmethod
    def _member_projects(user: User) -> Subquery:
        return Subquery(ProjectMember.filter(user_id=user.id).values('project_id'))

    @classmethod
    def projects(cls, user: User, organization_id: UUID) -> QuerySet[Project]:
        """Projects the user can see and file recordings into: public ones and private ones they belong to."""
        return Project.filter(
            cls.member_of_organization(user, organization_id), organization_id=organization_id
        ).filter(Q(is_private=False) | Q(id__in=cls._member_projects(user)))

    @classmethod
    def recording_rule(cls, user: User) -> Q:
        """The visibility rule without the organization and deletion filters."""
        shared = Q(visibility=RecordingVisibility.ORGANIZATION) & (
            Q(project_id=None)
            | Q(project_id__in=Subquery(Project.filter(is_private=False).values('id')))
            | Q(project_id__in=cls._member_projects(user))
        )
        return Q(created_by_id=user.id) | shared

    @classmethod
    def recordings(cls, user: User, organization_id: UUID, *, deleted: bool | None = False) -> QuerySet[Recording]:
        """
        Recordings the user can see in the organization. `deleted=False` (default) hides soft-deleted ones,
        `True` returns only them (trash, restore), `None` returns both (sync tombstones).
        """
        queryset = Recording.filter(
            cls.member_of_organization(user, organization_id), organization_id=organization_id
        ).filter(cls.recording_rule(user))
        if deleted is True:
            return queryset.filter(deleted_at__isnull=False)
        if deleted is False:
            return queryset.filter(deleted_at__isnull=True)
        return queryset

    @classmethod
    async def can_see_project(cls, user: User, project: Project) -> bool:
        return await cls.projects(user, project.organization_id).filter(id=project.id).exists()
