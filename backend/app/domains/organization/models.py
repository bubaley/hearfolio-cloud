from enum import StrEnum
from uuid import UUID

from tortoise import fields
from tortoise.expressions import Q, Subquery

from app.core.models import BaseModel
from app.core.scope import Scope
from app.core.utils.date_utils import as_utc, utcnow


def _memberships_of_user_organizations(user_id: UUID) -> Q:
    # A subquery instead of 'organization__org_users__user_id': Tortoise mis-aliases that self-join.
    member_org_ids = OrganizationUser.filter(user_id=user_id).values('organization_id')
    return Q(organization_id__in=Subquery(member_org_ids))


class OrganizationRole(StrEnum):
    OWNER = 'owner'
    ADMIN = 'admin'
    MEMBER = 'member'


ORGANIZATION_ADMIN_ROLES = (OrganizationRole.OWNER, OrganizationRole.ADMIN)


class OrganizationUser(BaseModel):
    organization = fields.ForeignKeyField(
        'models.Organization',
        related_name='org_users',
        on_delete=fields.CASCADE,
    )
    organization_id: UUID
    user = fields.ForeignKeyField('models.User', related_name='org_users', on_delete=fields.CASCADE)
    user_id: UUID
    role = fields.CharEnumField(OrganizationRole, max_length=16, default=OrganizationRole.MEMBER)

    tenant_scope = Scope(user=_memberships_of_user_organizations)

    class Meta:
        table = 'organization_user'
        unique_together = (('organization', 'user'),)
        ordering = ('created_at',)


class Organization(BaseModel):
    name = fields.CharField(max_length=128)
    key = fields.CharField(max_length=128, unique=True, db_index=True)

    tenant_scope = Scope(user='org_users__user_id')

    class Meta:
        ordering = ('created_at',)
        table = 'organization'


class InviteState(StrEnum):
    VALID = 'valid'
    EXPIRED = 'expired'
    USED = 'used'
    REVOKED = 'revoked'


class OrganizationInvite(BaseModel):
    """
    A single-use link that adds whoever accepts it to the organization with `role` (admin or member).
    Only the SHA-256 of the token is stored; the raw token is returned once, when the invite is created.
    """

    organization = fields.ForeignKeyField('models.Organization', related_name='invites', on_delete=fields.CASCADE)
    organization_id: UUID
    role = fields.CharEnumField(OrganizationRole, max_length=16, default=OrganizationRole.MEMBER)
    token_hash = fields.CharField(max_length=64, unique=True)
    created_by = fields.ForeignKeyField(
        'models.User', related_name='created_invites', null=True, on_delete=fields.SET_NULL
    )
    created_by_id: UUID | None
    expires_at = fields.DatetimeField()
    accepted_by = fields.ForeignKeyField(
        'models.User', related_name='accepted_invites', null=True, on_delete=fields.SET_NULL
    )
    accepted_by_id: UUID | None
    accepted_at = fields.DatetimeField(null=True)
    revoked_at = fields.DatetimeField(null=True)

    tenant_scope = Scope(user='organization__org_users__user_id', organization='organization_id')

    @property
    def state(self) -> InviteState:
        if self.revoked_at is not None:
            return InviteState.REVOKED
        if self.accepted_at is not None:
            return InviteState.USED
        if as_utc(self.expires_at) <= utcnow():
            return InviteState.EXPIRED
        return InviteState.VALID

    class Meta:
        table = 'organization_invite'
        ordering = ('-created_at',)
