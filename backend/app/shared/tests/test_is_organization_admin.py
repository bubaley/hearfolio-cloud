import pytest
from fastapi import APIRouter, FastAPI
from httpx2 import ASGITransport, AsyncClient

from app.conftest import TEST_ORIGIN
from app.core.exceptions import register_exceptions_handlers
from app.domains.organization.models import Organization, OrganizationRole, OrganizationUser
from app.shared.permissions.is_organization_admin import RequireOrgAdmin

router = APIRouter()


@router.get('/admin-only')
async def admin_only(auth_state: RequireOrgAdmin) -> dict[str, str]:
    assert auth_state.organization is not None
    return {'organization': auth_state.organization.key}


admin_app = FastAPI()
register_exceptions_handlers(admin_app)
admin_app.include_router(router)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('role', 'superuser', 'status'),
    [
        (OrganizationRole.OWNER, False, 200),
        (OrganizationRole.ADMIN, False, 200),
        (OrganizationRole.MEMBER, False, 403),
        (OrganizationRole.MEMBER, True, 200),
    ],
)
async def test_require_org_admin_dependency(db, user_factory, auth_headers, role, superuser, status):
    user = await user_factory(is_superuser=superuser)
    organization = await Organization.create(name='Org', key='org')
    await OrganizationUser.create(organization=organization, user=user, role=role)
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url=TEST_ORIGIN) as client:
        response = await client.get('/admin-only', headers=await auth_headers(user, organization))
    assert response.status_code == status
    if status == 200:
        assert response.json() == {'organization': 'org'}


@pytest.mark.asyncio
async def test_require_org_admin_needs_header_and_credentials(db, user_factory, auth_headers):
    user = await user_factory()
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url=TEST_ORIGIN) as client:
        assert (await client.get('/admin-only', headers=await auth_headers(user))).status_code == 400
        assert (await client.get('/admin-only')).status_code == 401
