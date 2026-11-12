import asyncio
import contextvars
from datetime import timedelta

import pytest
from tortoise import connections

from app.core.utils.date_utils import utcnow
from app.domains.oauth.models import OAuthAuthorizationCode
from app.domains.oauth.services.oauth_service import OAuthService
from app.domains.oauth.tests.test_oauth import (
    AUTHORIZE,
    TOKEN,
    _app_client,
    _authorize,
    _authorize_body,
    _pkce,
    _token_form,
)
from app.domains.organization.models import OrganizationInvite
from app.domains.organization.services.invite_service import InviteService
from app.domains.user.models import UserToken
from app.domains.user.services.user_service import UserService


@pytest.mark.asyncio
async def test_standard_authorize_params_are_tolerated(api_client, user_factory, auth_headers):
    user = await user_factory()
    headers = await auth_headers(user)
    _, challenge = _pkce()
    body = _authorize_body(challenge, response_type='code', scope='openid profile')
    assert (await api_client.get(AUTHORIZE, headers=headers, params=body)).status_code == 200
    assert (await api_client.post(AUTHORIZE, headers=headers, json=body)).status_code == 200

    body = _authorize_body(challenge, response_type='token')
    response = await api_client.post(AUTHORIZE, headers=headers, json=body)
    assert response.status_code == 400
    assert response.json()['error']['details']['error'] == 'invalid_request'


@pytest.mark.asyncio
async def test_reuse_during_the_exchange_still_revokes_the_token(api_client, user_factory, auth_headers, monkeypatch):
    """The second presentation arrives while the first one is creating the token: no token survives."""
    if connections.get('default').capabilities.dialect != 'postgres':
        pytest.skip('row locks (SELECT ... FOR UPDATE) need PostgreSQL')
    user = await user_factory()
    code, verifier = await _authorize(api_client, auth_headers, user)
    original = UserService.create_api_token
    outside = contextvars.copy_context()
    second_response = None

    async def create_api_token(*args, **kwargs):
        nonlocal second_response
        # The code is claimed and locked; a concurrent reuse must wait for the token to be linked.
        # The context from before the transaction: the other request must not share its connection.
        reuse = asyncio.create_task(_exchange(code, verifier), context=outside.copy())
        await asyncio.sleep(0.05)
        result = await original(*args, **kwargs)
        second_response = reuse
        return result

    async def _exchange(code_, verifier_):
        async with _app_client() as app_client:
            return await app_client.post(TOKEN, data=_token_form(code_, verifier_))

    monkeypatch.setattr(UserService, 'create_api_token', staticmethod(create_api_token))
    first = await _exchange(code, verifier)
    assert first.status_code == 200
    assert second_response is not None
    second = await second_response
    assert second.json()['error'] == 'invalid_grant'
    assert not await UserToken.exists(user=user)


@pytest.mark.asyncio
async def test_expired_codes_and_stale_invites_are_purged(user_factory, organization_factory):
    user = await user_factory()
    old = await OAuthAuthorizationCode.create(
        user=user,
        code_hash='a' * 64,
        client_id='hearfolio-app',
        redirect_uri='hearfolio://oauth/callback',
        code_challenge='c' * 43,
        device_name='Mac',
        expires_at=utcnow() - timedelta(days=2),
    )
    fresh = await OAuthAuthorizationCode.create(
        user=user,
        code_hash='b' * 64,
        client_id='hearfolio-app',
        redirect_uri='hearfolio://oauth/callback',
        code_challenge='c' * 43,
        device_name='Mac',
        expires_at=utcnow() + timedelta(seconds=60),
    )
    assert await OAuthService.purge_expired_codes() == 1
    assert not await OAuthAuthorizationCode.exists(id=old.id)
    assert await OAuthAuthorizationCode.exists(id=fresh.id)

    organization = await organization_factory()
    long_ago = utcnow() - timedelta(days=40)

    async def invite(token: str, **values):
        return await OrganizationInvite.create(
            organization=organization, token_hash=token * 64, expires_at=values.pop('expires_at', long_ago), **values
        )

    expired = await invite('e')
    revoked = await invite('r', expires_at=utcnow() + timedelta(days=1), revoked_at=long_ago)
    used = await invite('u', accepted_at=long_ago, accepted_by=user)
    valid = await invite('v', expires_at=utcnow() + timedelta(days=1))
    recently_expired = await invite('x', expires_at=utcnow() - timedelta(days=1))
    assert await InviteService.purge_stale() == 2
    remaining = set(await OrganizationInvite.all().values_list('id', flat=True))
    assert remaining == {used.id, valid.id, recently_expired.id}
    assert expired.id not in remaining and revoked.id not in remaining
