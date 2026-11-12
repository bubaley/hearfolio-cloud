from uuid import UUID

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.domains.organization.models import (
    ORGANIZATION_ADMIN_ROLES,
    Organization,
    OrganizationRole,
    OrganizationUser,
)
from app.domains.user.models import User

NOT_ADMIN = 'Only organization owners and admins can do this'
NOT_OWNER = 'Only organization owners can grant or revoke the owner role'
LAST_OWNER = 'The organization must keep at least one owner'


def _forbidden(message: str, reason: str) -> AppException:
    return AppException.from_attrs(ErrorCode.FORBIDDEN, message, details={'reason': reason})


class OrganizationService:
    """
    Organizations and their memberships. Role rules:

    - org admins (owner, admin, or a superuser) add and remove members and change roles
    - only owners (or superusers) grant or revoke `owner`, and remove an owner
    - every member may leave; the last owner can neither leave, be removed nor be demoted
    """

    @staticmethod
    async def create(organization: Organization, actor: User) -> Organization:
        async with in_transaction():
            await organization.save()
            await OrganizationUser.create(organization=organization, user=actor, role=OrganizationRole.OWNER)
        return organization

    # ROLES

    @staticmethod
    async def is_admin(user: User, organization_id: UUID) -> bool:
        """Owner/admin of the organization, or a superuser."""
        if user.is_superuser:
            return True
        return await OrganizationUser.filter(
            organization_id=organization_id, user_id=user.id, role__in=ORGANIZATION_ADMIN_ROLES
        ).exists()

    @staticmethod
    async def is_owner(user: User, organization_id: UUID) -> bool:
        """Owner of the organization, or a superuser."""
        if user.is_superuser:
            return True
        return await OrganizationUser.filter(
            organization_id=organization_id, user_id=user.id, role=OrganizationRole.OWNER
        ).exists()

    @staticmethod
    async def validate_admin(actor: User, organization_id: UUID) -> None:
        if not await OrganizationService.is_admin(actor, organization_id):
            raise _forbidden(NOT_ADMIN, 'not_admin')

    @staticmethod
    async def validate_owner(actor: User, organization_id: UUID) -> None:
        if not await OrganizationService.is_owner(actor, organization_id):
            raise _forbidden(NOT_OWNER, 'not_owner')

    @staticmethod
    async def _ensure_other_owner(membership: OrganizationUser) -> None:
        """Called inside a transaction: locks the owner rows so two owners cannot demote each other at once."""
        owners = await (
            OrganizationUser.filter(organization_id=membership.organization_id, role=OrganizationRole.OWNER)
            .select_for_update()
            .values_list('id', flat=True)
        )
        if not [owner_id for owner_id in owners if owner_id != membership.id]:
            raise AppException.from_attrs(ErrorCode.CONFLICT, LAST_OWNER, details={'reason': 'last_owner'})

    # MEMBERSHIPS

    @staticmethod
    async def add_member(membership: OrganizationUser, actor: User) -> OrganizationUser:
        """Add a user to `membership.organization_id`; the actor must be an org admin (owner to add an owner)."""
        await OrganizationService.validate_admin(actor, membership.organization_id)
        if membership.role == OrganizationRole.OWNER:
            await OrganizationService.validate_owner(actor, membership.organization_id)
        if not await Organization.exists(id=membership.organization_id):
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, 'Organization not found')
        try:
            await membership.save()
        except IntegrityError:
            if await OrganizationUser.filter(
                organization_id=membership.organization_id, user_id=membership.user_id
            ).exists():
                raise AppException.from_attrs(
                    ErrorCode.VALIDATION_ERROR,
                    'User is already in this organization',
                    details={'reason': 'already_member'},
                )
            raise
        return membership

    @staticmethod
    async def update_member(membership: OrganizationUser, actor: User) -> OrganizationUser:
        """Change the role. Touching `owner` (granting or revoking) needs an owner; the last owner stays."""
        await OrganizationService.validate_admin(actor, membership.organization_id)
        previous = await OrganizationUser.get(id=membership.id)
        new_role = membership.role or previous.role
        membership.role = new_role
        if OrganizationRole.OWNER in (previous.role, new_role) and previous.role != new_role:
            await OrganizationService.validate_owner(actor, membership.organization_id)
        async with in_transaction():
            if previous.role == OrganizationRole.OWNER and new_role != OrganizationRole.OWNER:
                await OrganizationService._ensure_other_owner(membership)
            await membership.save()
        return membership

    @staticmethod
    async def remove_member(membership: OrganizationUser, actor: User) -> None:
        """Admins remove members (owners remove owners); anyone may leave. The last owner cannot go."""
        if membership.user_id != actor.id:
            await OrganizationService.validate_admin(actor, membership.organization_id)
            if membership.role == OrganizationRole.OWNER:
                await OrganizationService.validate_owner(actor, membership.organization_id)
        async with in_transaction():
            if membership.role == OrganizationRole.OWNER:
                await OrganizationService._ensure_other_owner(membership)
            await membership.delete()

    @staticmethod
    async def add_invited_member(organization: Organization, user: User, role: OrganizationRole) -> OrganizationUser:
        """Join through an invite; the caller checked the invite. Already a member → 409, nothing changes."""
        try:
            return await OrganizationUser.create(organization=organization, user=user, role=role)
        except IntegrityError:
            raise AppException.from_attrs(
                ErrorCode.CONFLICT,
                'You are already a member of this organization',
                details={'reason': 'already_member'},
            )
