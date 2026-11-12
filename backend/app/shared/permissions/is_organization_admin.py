from fastapi import Request
from fastapi_ronin.generics import GenericViewSet
from fastapi_ronin.permissions import BasePermission

from app.core.auth import get_current_auth_state
from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.domains.organization.services.organization_service import OrganizationService


class IsOrganizationAdmin(BasePermission):
    """Owner/admin of the organization from `Organization-Key` (superusers pass). Requires the header."""

    PERMISSION_DENIED_MESSAGE = 'Only organization admins can do this'

    async def has_permission(self, request: Request, view: GenericViewSet) -> bool:
        state = get_current_auth_state()
        if state.user is None:
            return False
        if state.organization is None:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Organization-Key header is required')
        return await OrganizationService.is_admin(state.user, state.organization.id)
