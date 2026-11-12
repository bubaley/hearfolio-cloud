import importlib
from datetime import UTC, datetime

import pytest
from tortoise import connections

from app.domains.organization.models import OrganizationRole, OrganizationUser

backfill = importlib.import_module('migrations.0009_backfill_organization_owners')


@pytest.mark.asyncio
async def test_migration_promotes_the_earliest_member_of_ownerless_organizations(
    db, user_factory, organization_factory
):
    first, second, owner, member = [await user_factory() for _ in range(4)]
    ownerless = await organization_factory()
    owned = await organization_factory()
    await OrganizationUser.filter(organization_id__in=[ownerless.id, owned.id]).delete()
    early = await OrganizationUser.create(organization=ownerless, user=first, role=OrganizationRole.ADMIN)
    late = await OrganizationUser.create(organization=ownerless, user=second)
    await OrganizationUser.filter(id=early.id).update(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    await OrganizationUser.create(organization=owned, user=owner, role=OrganizationRole.OWNER)
    kept = await OrganizationUser.create(organization=owned, user=member)

    await connections.get('default').execute_script(backfill.PROMOTE_EARLIEST_MEMBER)

    assert (await OrganizationUser.get(id=early.id)).role == OrganizationRole.OWNER
    assert (await OrganizationUser.get(id=late.id)).role == OrganizationRole.MEMBER
    assert (await OrganizationUser.get(id=kept.id)).role == OrganizationRole.MEMBER
    assert await OrganizationUser.filter(organization=owned, role=OrganizationRole.OWNER).count() == 1
