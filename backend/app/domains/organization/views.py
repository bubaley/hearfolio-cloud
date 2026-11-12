from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Request, Response
from fastapi_ronin.decorators import action, viewset
from fastapi_ronin.permissions import IsAuthenticated

from app.core.auth import get_current_auth_state
from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.utils.request_utils import client_ip, public_base_url
from app.core.viewsets import BaseGenericViewSet, BaseModelViewSet, BaseReadOnlyViewSet
from app.domains.auth.services.auth_service import AuthService
from app.domains.auth.transport import set_auth_cookies
from app.domains.organization.filters import OrganizationFilterSet, OrganizationUserFilterSet
from app.domains.organization.models import Organization, OrganizationInvite, OrganizationUser
from app.domains.organization.schemas import (
    InviteAcceptedSchema,
    InviteAcceptSchema,
    InvitePreviewSchema,
    OrganizationCreateSchema,
    OrganizationInviteCreatedSchema,
    OrganizationInviteCreateSchema,
    OrganizationInviteReadSchema,
    OrganizationReadSchema,
    OrganizationUpdateSchema,
    OrganizationUserCreateSchema,
    OrganizationUserReadSchema,
    OrganizationUserUpdateSchema,
    UserOrganizationSchema,
)
from app.domains.organization.services.invite_service import InviteService
from app.domains.organization.services.organization_service import OrganizationService
from app.domains.user.models import User
from app.domains.user.schemas import UserReadSchema
from app.shared.permissions.is_organization_admin import IsOrganizationAdmin

organizations_router = APIRouter(prefix='/organizations', tags=['organizations'])
organization_users_router = APIRouter(prefix='/organization-users', tags=['organization-users'])
organization_invites_router = APIRouter(prefix='/organization-invites', tags=['organization-invites'])
invites_router = APIRouter(prefix='/invites', tags=['invites'])
me_router = APIRouter(prefix='/me', tags=['me'])
routers = (organizations_router, organization_users_router, organization_invites_router, invites_router, me_router)


@viewset(organizations_router)
class OrganizationViewSet(BaseModelViewSet[Organization]):
    model = Organization
    read_schema = OrganizationReadSchema
    create_schema = OrganizationCreateSchema
    update_schema = OrganizationUpdateSchema
    filterset_class = OrganizationFilterSet

    async def perform_create(self, obj: Organization) -> Organization:
        return await OrganizationService.create(obj, self.user)

    async def perform_update(self, obj: Organization) -> Organization:
        await OrganizationService.validate_admin(self.user, obj.id)
        await obj.save()
        return obj

    async def perform_destroy(self, obj: Organization) -> None:
        await OrganizationService.validate_owner(self.user, obj.id)
        await obj.delete()


@viewset(organization_users_router)
class OrganizationUserViewSet(BaseModelViewSet[OrganizationUser]):
    model = OrganizationUser
    read_schema = OrganizationUserReadSchema
    create_schema = OrganizationUserCreateSchema
    update_schema = OrganizationUserUpdateSchema
    filterset_class = OrganizationUserFilterSet
    # The organization comes from the body and is checked by OrganizationService, not from `Organization-Key`.
    organization_header = False

    async def get_queryset(self):
        user: User = self.user
        if user.is_superuser:
            return OrganizationUser.all()
        return await super().get_queryset()

    async def before_save(self, obj: OrganizationUser) -> None:
        pass

    async def perform_create(self, obj: OrganizationUser) -> OrganizationUser:
        return await OrganizationService.add_member(obj, self.user)

    async def perform_update(self, obj: OrganizationUser) -> OrganizationUser:
        return await OrganizationService.update_member(obj, self.user)

    async def perform_destroy(self, obj: OrganizationUser) -> None:
        await OrganizationService.remove_member(obj, self.user)


@viewset(organization_invites_router)
class OrganizationInviteViewSet(BaseReadOnlyViewSet[OrganizationInvite]):
    """Invite links of the `Organization-Key` organization; org admins only."""

    model = OrganizationInvite
    read_schema = OrganizationInviteReadSchema
    permission_classes = [IsAuthenticated, IsOrganizationAdmin]  # noqa: RUF012 - ronin declares a list

    @action(methods=['POST'], status_code=201)
    async def create(self, request: Request, data: OrganizationInviteCreateSchema) -> OrganizationInviteCreatedSchema:
        """Create an invite. The token and the link are returned only here."""
        organization = get_current_auth_state().organization
        if organization is None:  # IsOrganizationAdmin already requires the header
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Organization-Key header is required')
        invite, token = await InviteService.create(organization, self.user, data)
        read = await OrganizationInviteReadSchema.from_tortoise_orm(invite)
        return OrganizationInviteCreatedSchema(
            **read.model_dump(), token=token, url=f'{public_base_url(request)}/invite/{token}'
        )

    @action(methods=['POST'], detail=True)
    async def revoke(self, item_id: UUID) -> OrganizationInviteReadSchema:
        """Revoke an unused invite; its link stops working."""
        invite = await InviteService.revoke(await self.get_object(item_id))
        return await OrganizationInviteReadSchema.from_tortoise_orm(invite)


@viewset(invites_router)
class InviteViewSet(BaseGenericViewSet[OrganizationInvite]):
    """Public invite links (`/invite/{token}` in the web app). Rate limited per client IP."""

    model = OrganizationInvite
    read_schema = OrganizationInviteReadSchema
    organization_header = False

    def get_permissions(self):
        return []

    @action(methods=['GET'], path='{token}')
    async def preview(self, request: Request, token: str) -> InvitePreviewSchema:
        """Organization, role, inviter and state (`valid | expired | used | revoked`) of an invite."""
        return InviteService.preview(await InviteService.get_by_token(token, client_ip(request)))

    @action(methods=['POST'], path='{token}/accept')
    async def accept(
        self,
        request: Request,
        response: Response,
        token: str,
        data: Annotated[InviteAcceptSchema | None, Body()] = None,
    ) -> InviteAcceptedSchema:
        """
        Join the organization. Signed in: the body is ignored. Anonymous: `{name, email, password}` creates the
        account, signs it in (sets the session cookies) and joins.
        """
        invite = await InviteService.get_by_token(token, client_ip(request))
        user: User | None = self.user
        if user is not None:
            membership = await InviteService.accept(invite, user)
        elif data is not None:
            user, membership = await InviteService.accept_with_registration(invite, data, client_ip(request))
            set_auth_cookies(response, await AuthService.start_session(user))
        else:
            raise AppException.from_attrs(
                ErrorCode.UNAUTHORIZED,
                'Sign in or send name, email and password to accept the invite',
                details={'reason': 'registration_required'},
            )
        return InviteAcceptedSchema(
            user=await UserReadSchema.from_tortoise_orm(user),
            organization=await OrganizationReadSchema.from_tortoise_orm(invite.organization),
            role=membership.role,
        )


@viewset(me_router)
class MeViewSet(BaseGenericViewSet[Organization]):
    """The caller's own data that needs no `Organization-Key`."""

    model = Organization
    read_schema = OrganizationReadSchema

    @action(methods=['GET'])
    async def organizations(self) -> list[UserOrganizationSchema]:
        """Organizations the caller belongs to, with the caller's role in each."""
        return await UserOrganizationSchema.for_user(self.user.id)
