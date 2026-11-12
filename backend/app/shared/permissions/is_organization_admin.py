from typing import Annotated

from fastapi import Depends, Request
from fastapi_ronin.generics import GenericViewSet
from fastapi_ronin.permissions import BasePermission

from app.core.auth import AuthState, get_auth_state, get_current_auth_state
from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.domains.organization.services.organization_service import OrganizationService

ORGANIZATION_KEY_REQUIRED = 'Organization-Key header is required'


class IsOrganizationAdmin(BasePermission):
    """
    Owner/admin of the organization from `Organization-Key` (superusers pass). Requires the header (400),
    members get 403. Use `permission_classes = [IsAuthenticated, IsOrganizationAdmin]`, or return it from
    `get_permissions()` for the write actions only. Plain routes: the `RequireOrgAdmin` dependency below.
    """

    PERMISSION_DENIED_MESSAGE = 'Only organization admins can do this'

    async def has_permission(self, request: Request, view: GenericViewSet) -> bool:
        state = get_current_auth_state()
        if state.user is None:
            return False
        if state.organization is None:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, ORGANIZATION_KEY_REQUIRED)
        return await OrganizationService.is_admin(state.user, state.organization.id)


async def require_organization_admin(auth_state: Annotated[AuthState, Depends(get_auth_state)]) -> AuthState:
    """`IsOrganizationAdmin` as a FastAPI dependency for routes outside a viewset."""
    if auth_state.user is None:
        raise AppException.from_attrs(ErrorCode.UNAUTHORIZED, 'Could not validate credentials')
    if auth_state.organization is None:
        raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, ORGANIZATION_KEY_REQUIRED)
    if not await OrganizationService.is_admin(auth_state.user, auth_state.organization.id):
        raise AppException.from_attrs(ErrorCode.FORBIDDEN, IsOrganizationAdmin.PERMISSION_DENIED_MESSAGE)
    return auth_state


RequireOrgAdmin = Annotated[AuthState, Depends(require_organization_admin)]
