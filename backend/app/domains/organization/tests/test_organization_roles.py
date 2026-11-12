from uuid import uuid4

import pytest

from app.domains.organization.models import Organization, OrganizationRole, OrganizationUser
from app.domains.organization.services.organization_service import OrganizationService

MEMBERS = '/api/v1/organization-users'


async def _org_with(
    roles: dict[str, OrganizationRole], user_factory
) -> tuple[Organization, dict[str, OrganizationUser]]:
    organization = await Organization.create(name='Org', key=f'org-{uuid4().hex[:8]}')
    memberships = {}
    for name, role in roles.items():
        memberships[name] = await OrganizationUser.create(
            organization=organization, user=await user_factory(), role=role
        )
    return organization, memberships


async def _headers(auth_headers, membership: OrganizationUser) -> dict[str, str]:
    await membership.fetch_related('user')
    return await auth_headers(membership.user)


# ADD MEMBERS


@pytest.mark.asyncio
async def test_plain_member_cannot_add_members(api_client, user_factory, auth_headers):
    organization, people = await _org_with({'member': OrganizationRole.MEMBER}, user_factory)
    added = await user_factory()
    response = await api_client.post(
        MEMBERS,
        headers=await _headers(auth_headers, people['member']),
        json={'organization_id': str(organization.id), 'user_id': str(added.id)},
    )
    assert response.status_code == 403
    assert response.json()['error']['details']['reason'] == 'not_admin'
    assert not await OrganizationUser.exists(organization=organization, user=added)


@pytest.mark.asyncio
async def test_admin_adds_member_with_role_but_cannot_add_owner(api_client, user_factory, auth_headers):
    organization, people = await _org_with({'admin': OrganizationRole.ADMIN}, user_factory)
    headers = await _headers(auth_headers, people['admin'])
    added = await user_factory()
    response = await api_client.post(
        MEMBERS,
        headers=headers,
        json={'organization_id': str(organization.id), 'user_id': str(added.id), 'role': 'admin'},
    )
    assert response.status_code == 201
    assert response.json()['role'] == 'admin'

    other = await user_factory()
    response = await api_client.post(
        MEMBERS,
        headers=headers,
        json={'organization_id': str(organization.id), 'user_id': str(other.id), 'role': 'owner'},
    )
    assert response.status_code == 403
    assert response.json()['error']['details']['reason'] == 'not_owner'
    assert not await OrganizationUser.exists(organization=organization, user=other)


@pytest.mark.asyncio
async def test_owner_can_add_owner(api_client, user_factory, auth_headers):
    organization, people = await _org_with({'owner': OrganizationRole.OWNER}, user_factory)
    added = await user_factory()
    response = await api_client.post(
        MEMBERS,
        headers=await _headers(auth_headers, people['owner']),
        json={'organization_id': str(organization.id), 'user_id': str(added.id), 'role': 'owner'},
    )
    assert response.status_code == 201
    assert (await OrganizationUser.get(organization=organization, user=added)).role == OrganizationRole.OWNER


@pytest.mark.asyncio
async def test_admin_of_one_organization_cannot_escalate_in_another(api_client, user_factory, auth_headers):
    """Being admin somewhere does not help in an organization where the user is a plain member."""
    home, people = await _org_with({'admin': OrganizationRole.ADMIN}, user_factory)
    foreign, foreign_people = await _org_with(
        {'owner': OrganizationRole.OWNER, 'member': OrganizationRole.MEMBER}, user_factory
    )
    actor = people['admin']
    actor_in_foreign = await OrganizationUser.create(organization=foreign, user_id=actor.user_id)
    headers = {**await _headers(auth_headers, actor), 'Organization-Key': home.key}

    response = await api_client.patch(f'{MEMBERS}/{actor_in_foreign.id}', headers=headers, json={'role': 'admin'})
    assert response.status_code == 403
    response = await api_client.patch(
        f'{MEMBERS}/{foreign_people["member"].id}', headers=headers, json={'role': 'admin'}
    )
    assert response.status_code == 403
    response = await api_client.delete(f'{MEMBERS}/{foreign_people["owner"].id}', headers=headers)
    assert response.status_code == 403
    assert (await OrganizationUser.get(id=actor_in_foreign.id)).role == OrganizationRole.MEMBER
    assert await OrganizationUser.exists(id=foreign_people['owner'].id)


# CHANGE ROLES


@pytest.mark.asyncio
async def test_admin_changes_member_and_admin_roles(api_client, user_factory, auth_headers):
    _, people = await _org_with(
        {'admin': OrganizationRole.ADMIN, 'member': OrganizationRole.MEMBER, 'other_admin': OrganizationRole.ADMIN},
        user_factory,
    )
    headers = await _headers(auth_headers, people['admin'])
    response = await api_client.patch(f'{MEMBERS}/{people["member"].id}', headers=headers, json={'role': 'admin'})
    assert response.status_code == 200
    assert response.json()['role'] == 'admin'
    response = await api_client.patch(f'{MEMBERS}/{people["other_admin"].id}', headers=headers, json={'role': 'member'})
    assert response.status_code == 200
    assert (await OrganizationUser.get(id=people['other_admin'].id)).role == OrganizationRole.MEMBER


@pytest.mark.asyncio
async def test_member_cannot_promote_themselves(api_client, user_factory, auth_headers):
    _, people = await _org_with({'owner': OrganizationRole.OWNER, 'member': OrganizationRole.MEMBER}, user_factory)
    response = await api_client.patch(
        f'{MEMBERS}/{people["member"].id}',
        headers=await _headers(auth_headers, people['member']),
        json={'role': 'owner'},
    )
    assert response.status_code == 403
    assert (await OrganizationUser.get(id=people['member'].id)).role == OrganizationRole.MEMBER


@pytest.mark.asyncio
async def test_admin_cannot_grant_or_revoke_owner(api_client, user_factory, auth_headers):
    _, people = await _org_with(
        {'owner': OrganizationRole.OWNER, 'admin': OrganizationRole.ADMIN, 'member': OrganizationRole.MEMBER},
        user_factory,
    )
    headers = await _headers(auth_headers, people['admin'])
    response = await api_client.patch(f'{MEMBERS}/{people["member"].id}', headers=headers, json={'role': 'owner'})
    assert response.status_code == 403
    response = await api_client.patch(f'{MEMBERS}/{people["admin"].id}', headers=headers, json={'role': 'owner'})
    assert response.status_code == 403
    response = await api_client.patch(f'{MEMBERS}/{people["owner"].id}', headers=headers, json={'role': 'member'})
    assert response.status_code == 403
    response = await api_client.delete(f'{MEMBERS}/{people["owner"].id}', headers=headers)
    assert response.status_code == 403
    assert (await OrganizationUser.get(id=people['owner'].id)).role == OrganizationRole.OWNER


@pytest.mark.asyncio
async def test_owner_transfers_ownership_then_steps_down(api_client, user_factory, auth_headers):
    _, people = await _org_with({'owner': OrganizationRole.OWNER, 'admin': OrganizationRole.ADMIN}, user_factory)
    headers = await _headers(auth_headers, people['owner'])
    response = await api_client.patch(f'{MEMBERS}/{people["admin"].id}', headers=headers, json={'role': 'owner'})
    assert response.status_code == 200
    response = await api_client.patch(f'{MEMBERS}/{people["owner"].id}', headers=headers, json={'role': 'admin'})
    assert response.status_code == 200
    assert (await OrganizationUser.get(id=people['owner'].id)).role == OrganizationRole.ADMIN


@pytest.mark.asyncio
async def test_last_owner_cannot_be_demoted_or_removed_even_by_superuser(api_client, user_factory, auth_headers):
    _, people = await _org_with({'owner': OrganizationRole.OWNER}, user_factory)
    for headers in (
        await _headers(auth_headers, people['owner']),
        await auth_headers(await user_factory(is_superuser=True)),
    ):
        response = await api_client.patch(f'{MEMBERS}/{people["owner"].id}', headers=headers, json={'role': 'admin'})
        assert response.status_code == 409
        assert response.json()['error']['details']['reason'] == 'last_owner'
        response = await api_client.delete(f'{MEMBERS}/{people["owner"].id}', headers=headers)
        assert response.status_code == 409
    assert (await OrganizationUser.get(id=people['owner'].id)).role == OrganizationRole.OWNER


@pytest.mark.asyncio
async def test_patch_without_role_keeps_it(api_client, user_factory, auth_headers):
    _, people = await _org_with({'owner': OrganizationRole.OWNER, 'admin': OrganizationRole.ADMIN}, user_factory)
    response = await api_client.patch(
        f'{MEMBERS}/{people["admin"].id}', headers=await _headers(auth_headers, people['owner']), json={}
    )
    assert response.status_code == 200
    assert response.json()['role'] == 'admin'


@pytest.mark.asyncio
async def test_superuser_grants_owner_without_membership(api_client, user_factory, auth_headers):
    _, people = await _org_with({'owner': OrganizationRole.OWNER, 'member': OrganizationRole.MEMBER}, user_factory)
    superuser = await user_factory(is_superuser=True)
    response = await api_client.patch(
        f'{MEMBERS}/{people["member"].id}', headers=await auth_headers(superuser), json={'role': 'owner'}
    )
    assert response.status_code == 200
    assert response.json()['role'] == 'owner'


# REMOVE AND LEAVE


@pytest.mark.asyncio
async def test_member_leaves_but_cannot_remove_others(api_client, user_factory, auth_headers):
    _, people = await _org_with(
        {'owner': OrganizationRole.OWNER, 'member': OrganizationRole.MEMBER, 'other': OrganizationRole.MEMBER},
        user_factory,
    )
    headers = await _headers(auth_headers, people['member'])
    response = await api_client.delete(f'{MEMBERS}/{people["other"].id}', headers=headers)
    assert response.status_code == 403
    response = await api_client.delete(f'{MEMBERS}/{people["member"].id}', headers=headers)
    assert response.status_code == 204
    assert not await OrganizationUser.exists(id=people['member'].id)


@pytest.mark.asyncio
async def test_owner_leaves_only_while_another_owner_remains(api_client, user_factory, auth_headers):
    _, people = await _org_with({'owner': OrganizationRole.OWNER, 'second': OrganizationRole.OWNER}, user_factory)
    response = await api_client.delete(
        f'{MEMBERS}/{people["owner"].id}', headers=await _headers(auth_headers, people['owner'])
    )
    assert response.status_code == 204
    response = await api_client.delete(
        f'{MEMBERS}/{people["second"].id}', headers=await _headers(auth_headers, people['second'])
    )
    assert response.status_code == 409
    assert await OrganizationUser.exists(id=people['second'].id)


@pytest.mark.asyncio
async def test_admin_removes_admin_and_member(api_client, user_factory, auth_headers):
    _, people = await _org_with(
        {'admin': OrganizationRole.ADMIN, 'other_admin': OrganizationRole.ADMIN, 'member': OrganizationRole.MEMBER},
        user_factory,
    )
    headers = await _headers(auth_headers, people['admin'])
    for target in ('other_admin', 'member'):
        response = await api_client.delete(f'{MEMBERS}/{people[target].id}', headers=headers)
        assert response.status_code == 204


@pytest.mark.asyncio
async def test_is_admin_and_is_owner(db, user_factory):
    organization, people = await _org_with(
        {'owner': OrganizationRole.OWNER, 'admin': OrganizationRole.ADMIN, 'member': OrganizationRole.MEMBER},
        user_factory,
    )
    for membership in people.values():
        await membership.fetch_related('user')
    assert await OrganizationService.is_admin(people['owner'].user, organization.id)
    assert await OrganizationService.is_admin(people['admin'].user, organization.id)
    assert not await OrganizationService.is_admin(people['member'].user, organization.id)
    assert not await OrganizationService.is_owner(people['admin'].user, organization.id)
    assert await OrganizationService.is_owner(await user_factory(is_superuser=True), organization.id)


# ORGANIZATION SETTINGS


@pytest.mark.asyncio
async def test_only_admins_rename_and_only_owners_delete_the_organization(api_client, user_factory, auth_headers):
    organization, people = await _org_with(
        {'owner': OrganizationRole.OWNER, 'admin': OrganizationRole.ADMIN, 'member': OrganizationRole.MEMBER},
        user_factory,
    )
    url = f'/api/v1/organizations/{organization.id}'
    response = await api_client.patch(url, headers=await _headers(auth_headers, people['member']), json={'name': 'X'})
    assert response.status_code == 403
    response = await api_client.patch(url, headers=await _headers(auth_headers, people['admin']), json={'name': 'New'})
    assert response.status_code == 200
    response = await api_client.delete(url, headers=await _headers(auth_headers, people['admin']))
    assert response.status_code == 403
    response = await api_client.delete(url, headers=await _headers(auth_headers, people['owner']))
    assert response.status_code == 204


# ME


@pytest.mark.asyncio
async def test_me_organizations_lists_own_memberships_with_role(api_client, user_factory, auth_headers):
    user = await user_factory()
    first = await Organization.create(name='First', key='first')
    second = await Organization.create(name='Second', key='second')
    await Organization.create(name='Foreign', key='foreign')
    await OrganizationUser.create(organization=first, user=user, role=OrganizationRole.OWNER)
    await OrganizationUser.create(organization=second, user=user)

    response = await api_client.get('/api/v1/me/organizations', headers=await auth_headers(user))

    assert response.status_code == 200
    assert [(item['key'], item['role']) for item in response.json()] == [('first', 'owner'), ('second', 'member')]
    me = await api_client.get('/api/v1/auth/me', headers=await auth_headers(user))
    assert [(item['key'], item['role']) for item in me.json()['organizations']] == [
        ('first', 'owner'),
        ('second', 'member'),
    ]


@pytest.mark.asyncio
async def test_me_organizations_requires_authentication(api_client):
    response = await api_client.get('/api/v1/me/organizations')
    assert response.status_code == 401
