from datetime import timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient

from app.conftest import TEST_ORIGIN, TEST_PASSWORD
from app.core.services.crypto_service import CryptoService
from app.core.settings import settings
from app.core.utils.date_utils import utcnow
from app.domains.organization.models import Organization, OrganizationInvite, OrganizationRole, OrganizationUser
from app.domains.user.models import User
from app.main import app

INVITES = '/api/v1/organization-invites'
NEW_ACCOUNT = {'name': 'Анна Иванова', 'email': 'Anna@Example.test', 'password': 'long-enough-password'}


async def _org_admin(user_factory, role: OrganizationRole = OrganizationRole.OWNER) -> tuple[Organization, User]:
    admin = await user_factory()
    organization = await Organization.create(name='Acme', key='acme')
    await OrganizationUser.create(organization=organization, user=admin, role=role)
    return organization, admin


async def _create_invite(api_client, auth_headers, admin: User, organization: Organization, **body) -> dict:
    response = await api_client.post(INVITES, headers=await auth_headers(admin, organization), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _anonymous_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=TEST_ORIGIN, headers={'Origin': TEST_ORIGIN})


# ADMIN


@pytest.mark.asyncio
async def test_admin_creates_invite_and_only_the_hash_is_stored(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory, OrganizationRole.ADMIN)
    body = await _create_invite(api_client, auth_headers, admin, organization, role='admin')

    assert body['role'] == 'admin'
    assert body['state'] == 'valid'
    assert body['url'] == f'{TEST_ORIGIN}/invite/{body["token"]}'
    assert body['created_by']['id'] == str(admin.id)
    invite = await OrganizationInvite.get(id=body['id'])
    assert invite.token_hash == CryptoService.hash_value(body['token'])
    assert body['token'] not in invite.token_hash
    assert timedelta(days=6, hours=23) < invite.expires_at - utcnow() <= timedelta(days=7)

    listed = await api_client.get(INVITES, headers=await auth_headers(admin, organization))
    assert listed.status_code == 200
    assert [item['id'] for item in listed.json()['data']] == [body['id']]
    assert 'token' not in listed.json()['data'][0]


@pytest.mark.asyncio
async def test_invite_link_uses_public_url(api_client, user_factory, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, 'public_url', 'https://rec.example.com/')
    organization, admin = await _org_admin(user_factory)
    body = await _create_invite(api_client, auth_headers, admin, organization)
    assert body['url'] == f'https://rec.example.com/invite/{body["token"]}'


@pytest.mark.asyncio
async def test_invite_cannot_grant_owner(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    response = await api_client.post(INVITES, headers=await auth_headers(admin, organization), json={'role': 'owner'})
    assert response.status_code == 422
    assert not await OrganizationInvite.exists()


@pytest.mark.asyncio
async def test_member_cannot_manage_invites(api_client, user_factory, auth_headers):
    organization, _ = await _org_admin(user_factory)
    member = await user_factory()
    await OrganizationUser.create(organization=organization, user=member)
    headers = await auth_headers(member, organization)
    assert (await api_client.get(INVITES, headers=headers)).status_code == 403
    assert (await api_client.post(INVITES, headers=headers, json={})).status_code == 403


@pytest.mark.asyncio
async def test_invites_require_organization_key(api_client, user_factory, auth_headers):
    _, admin = await _org_admin(user_factory)
    response = await api_client.get(INVITES, headers=await auth_headers(admin))
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_admin_sees_and_revokes_only_own_organization_invites(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    other_admin = await user_factory()
    other = await Organization.create(name='Other', key='other')
    await OrganizationUser.create(organization=other, user=other_admin, role=OrganizationRole.OWNER)
    foreign = await _create_invite(api_client, auth_headers, other_admin, other)

    headers = await auth_headers(admin, organization)
    assert (await api_client.get(INVITES, headers=headers)).json()['data'] == []
    response = await api_client.post(f'{INVITES}/{foreign["id"]}/revoke', headers=headers)
    assert response.status_code == 404
    assert (await OrganizationInvite.get(id=foreign['id'])).revoked_at is None


@pytest.mark.asyncio
async def test_revoked_invite_cannot_be_viewed_as_valid_or_accepted(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization)
    response = await api_client.post(
        f'{INVITES}/{invite["id"]}/revoke', headers=await auth_headers(admin, organization)
    )
    assert response.status_code == 200
    assert response.json()['state'] == 'revoked'

    async with _anonymous_client() as anonymous:
        preview = await anonymous.get(f'/api/v1/invites/{invite["token"]}')
        assert preview.json()['state'] == 'revoked'
        response = await anonymous.post(f'/api/v1/invites/{invite["token"]}/accept', json=NEW_ACCOUNT)
    assert response.status_code == 409
    assert response.json()['error']['details']['reason'] == 'invite_revoked'
    assert not await User.exists(email='anna@example.test')


# PUBLIC


@pytest.mark.asyncio
async def test_public_preview(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization, role='admin')
    async with _anonymous_client() as anonymous:
        response = await anonymous.get(f'/api/v1/invites/{invite["token"]}')
    assert response.status_code == 200
    assert response.json() == {
        'organization_name': 'Acme',
        'role': 'admin',
        'inviter_name': 'Test User',
        'state': 'valid',
        'expires_at': response.json()['expires_at'],
    }


@pytest.mark.asyncio
async def test_unknown_token_is_404_and_rate_limited(api_client, monkeypatch):
    monkeypatch.setattr(settings, 'public_rate_limit_attempts', 3)
    for _ in range(3):
        response = await api_client.get('/api/v1/invites/unknown-token')
        assert response.status_code == 404
        assert response.json()['error']['details']['reason'] == 'invite_not_found'
    response = await api_client.get('/api/v1/invites/unknown-token')
    assert response.status_code == 429
    assert int(response.headers['retry-after']) > 0
    response = await api_client.post('/api/v1/invites/unknown-token/accept', json=NEW_ACCOUNT)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_anonymous_accept_registers_signs_in_and_joins(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization, role='admin')

    async with _anonymous_client() as anonymous:
        response = await anonymous.post(f'/api/v1/invites/{invite["token"]}/accept', json=NEW_ACCOUNT)
        assert response.status_code == 200, response.text
        assert {'access_token', 'refresh_token'} <= set(anonymous.cookies.keys())
        me = await anonymous.get('/api/v1/auth/me')

    body = response.json()
    assert body['role'] == 'admin'
    assert body['organization']['id'] == str(organization.id)
    user = await User.get(email='anna@example.test')
    assert (user.first_name, user.last_name) == ('Анна', 'Иванова')
    assert await user.verify_password_async(NEW_ACCOUNT['password'])
    assert not user.is_superuser
    assert (await OrganizationUser.get(organization=organization, user=user)).role == OrganizationRole.ADMIN
    assert me.status_code == 200
    assert [(org['key'], org['role']) for org in me.json()['organizations']] == [('acme', 'admin')]
    stored = await OrganizationInvite.get(id=invite['id'])
    assert stored.accepted_by_id == user.id
    assert stored.state == 'used'


@pytest.mark.asyncio
async def test_invite_is_single_use(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization)
    async with _anonymous_client() as anonymous:
        assert (await anonymous.post(f'/api/v1/invites/{invite["token"]}/accept', json=NEW_ACCOUNT)).status_code == 200
    second = await user_factory()
    response = await api_client.post(f'/api/v1/invites/{invite["token"]}/accept', headers=await auth_headers(second))
    assert response.status_code == 409
    assert response.json()['error']['details']['reason'] == 'invite_used'
    assert not await OrganizationUser.exists(organization=organization, user=second)
    response = await api_client.post(
        f'{INVITES}/{invite["id"]}/revoke', headers=await auth_headers(admin, organization)
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_expired_invite(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization)
    await OrganizationInvite.filter(id=invite['id']).update(expires_at=utcnow() - timedelta(seconds=1))
    user = await user_factory()
    preview = await api_client.get(f'/api/v1/invites/{invite["token"]}')
    assert preview.json()['state'] == 'expired'
    response = await api_client.post(f'/api/v1/invites/{invite["token"]}/accept', headers=await auth_headers(user))
    assert response.status_code == 409
    assert response.json()['error']['details']['reason'] == 'invite_expired'


@pytest.mark.asyncio
async def test_anonymous_accept_with_existing_email_asks_to_sign_in(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization)
    existing = await user_factory(email='anna@example.test')
    async with _anonymous_client() as anonymous:
        response = await anonymous.post(f'/api/v1/invites/{invite["token"]}/accept', json=NEW_ACCOUNT)
        assert 'access_token' not in anonymous.cookies
    assert response.status_code == 409
    assert response.json()['error']['message'] == 'Войдите, чтобы принять приглашение'
    assert response.json()['error']['details']['reason'] == 'email_exists'
    assert await existing.verify_password_async(TEST_PASSWORD)
    assert (await OrganizationInvite.get(id=invite['id'])).state == 'valid'


@pytest.mark.asyncio
async def test_signed_in_accept_joins_with_invite_role(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization)
    user = await user_factory()
    response = await api_client.post(
        f'/api/v1/invites/{invite["token"]}/accept', headers=await auth_headers(user), json=NEW_ACCOUNT
    )
    assert response.status_code == 200
    assert response.json()['user']['id'] == str(user.id)
    assert response.json()['role'] == 'member'
    assert not await User.exists(email='anna@example.test')


@pytest.mark.asyncio
async def test_already_member_gets_409_and_invite_stays_usable(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization, role='admin')
    response = await api_client.post(f'/api/v1/invites/{invite["token"]}/accept', headers=await auth_headers(admin))
    assert response.status_code == 409
    assert response.json()['error']['details']['reason'] == 'already_member'
    assert (await OrganizationUser.get(organization=organization, user=admin)).role == OrganizationRole.OWNER
    assert (await OrganizationInvite.get(id=invite['id'])).state == 'valid'


@pytest.mark.asyncio
async def test_anonymous_accept_without_account_data_is_401(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization)
    async with _anonymous_client() as anonymous:
        response = await anonymous.post(f'/api/v1/invites/{invite["token"]}/accept')
    assert response.status_code == 401
    assert response.json()['error']['details']['reason'] == 'registration_required'


@pytest.mark.asyncio
async def test_anonymous_accept_validates_password_policy(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization)
    async with _anonymous_client() as anonymous:
        response = await anonymous.post(
            f'/api/v1/invites/{invite["token"]}/accept', json={**NEW_ACCOUNT, 'password': 'short'}
        )
    assert response.status_code == 422
    assert (await OrganizationInvite.get(id=invite['id'])).state == 'valid'


@pytest.mark.asyncio
async def test_cookie_accept_from_foreign_origin_is_rejected(api_client, user_factory, auth_headers):
    organization, admin = await _org_admin(user_factory)
    invite = await _create_invite(api_client, auth_headers, admin, organization)
    user = await user_factory()
    login = await api_client.post('/api/v1/auth/login', json={'email': user.email, 'password': TEST_PASSWORD})
    assert login.status_code == 200
    response = await api_client.post(
        f'/api/v1/invites/{invite["token"]}/accept', headers={'Origin': 'https://evil.example'}
    )
    assert response.status_code == 403
    assert not await OrganizationUser.exists(organization=organization, user=user)
