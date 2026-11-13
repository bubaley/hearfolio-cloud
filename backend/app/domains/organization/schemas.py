from datetime import datetime
from uuid import UUID

from fastapi_ronin.decorators import schema
from pydantic import ConfigDict, Field, field_validator

from app.core.fields.email_field import NormalizedEmail
from app.core.fields.password_field import NewPassword
from app.core.models import BaseCreateSchema, BaseReadSchema, BaseSchema
from app.core.settings import settings
from app.domains.organization.models import (
    InviteState,
    Organization,
    OrganizationInvite,
    OrganizationRole,
    OrganizationUser,
)
from app.domains.user.schemas import UserReadSchema

# ORGANIZATION_SCHEMAS


@schema(model=Organization)
class OrganizationCreateSchema(BaseCreateSchema):
    name: str
    key: str


@schema(model=Organization)
class OrganizationUpdateSchema(BaseCreateSchema):
    name: str


@schema(model=Organization)
class OrganizationReadSchema(BaseReadSchema, OrganizationCreateSchema):
    pass


class UserOrganizationSchema(OrganizationReadSchema):
    """An organization of the current user together with the user's role in it."""

    role: OrganizationRole

    @classmethod
    async def for_user(cls, user_id: UUID) -> list[UserOrganizationSchema]:
        memberships = await (
            OrganizationUser.filter(user_id=user_id)
            .select_related('organization')
            .order_by('organization__created_at', 'organization_id')
        )
        return [
            cls(
                **OrganizationReadSchema.model_validate(membership.organization).model_dump(),
                role=membership.role,
            )
            for membership in memberships
        ]


# ORGANIZATION_USER_SCHEMAS


@schema(model=OrganizationUser)
class OrganizationUserCreateSchema(BaseCreateSchema):
    """The organization is explicit (not `Organization-Key`): members are managed from the organization's page."""

    organization_id: UUID
    user_id: UUID
    role: OrganizationRole = OrganizationRole.MEMBER


@schema(model=OrganizationUser)
class OrganizationUserUpdateSchema(BaseCreateSchema):
    """Only the role changes; user and organization are fixed after creation. Omitted role → unchanged."""

    role: OrganizationRole | None = None

    model_config = ConfigDict(extra='forbid')


@schema(model=OrganizationUser)
class OrganizationUserReadSchema(BaseReadSchema, OrganizationUserCreateSchema):
    user: UserReadSchema


# ORGANIZATION_INVITE_SCHEMAS


class OrganizationInviteCreateSchema(BaseCreateSchema):
    role: OrganizationRole = OrganizationRole.MEMBER
    expires_in_days: int = Field(default_factory=lambda: settings.invite_expire_days, ge=1, le=30)

    model_config = ConfigDict(extra='forbid')

    @field_validator('role')
    @classmethod
    def validate_role(cls, value: OrganizationRole) -> OrganizationRole:
        if value == OrganizationRole.OWNER:
            raise ValueError('An invite grants admin or member, never owner')
        return value


@schema(model=OrganizationInvite)
class OrganizationInviteReadSchema(BaseReadSchema):
    organization_id: UUID
    role: OrganizationRole
    state: InviteState
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_by: UserReadSchema | None
    accepted_by: UserReadSchema | None


@schema(model=OrganizationInvite)
class OrganizationInviteCreatedSchema(OrganizationInviteReadSchema):
    """Returned once on creation: the raw token and the link to share. Neither can be read again."""

    token: str
    url: str


class InvitePreviewSchema(BaseSchema):
    """What the public invite page shows before accepting."""

    organization_name: str
    role: OrganizationRole
    inviter_name: str | None
    state: InviteState
    expires_at: datetime
    # The signed-in caller already belongs to the organization (always false for anonymous visitors).
    already_member: bool = False


class InviteAcceptSchema(BaseSchema):
    """Anonymous accept: the account to create. Ignored when the request is signed in."""

    name: str = Field(min_length=1, max_length=255)
    email: NormalizedEmail
    password: NewPassword


class InviteAcceptedSchema(BaseSchema):
    user: UserReadSchema
    organization: OrganizationReadSchema
    role: OrganizationRole
