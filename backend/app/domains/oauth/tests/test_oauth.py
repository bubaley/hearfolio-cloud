import secrets
from datetime import timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient

from app.conftest import TEST_ORIGIN, TEST_PASSWORD
from app.core.services.crypto_service import CryptoService
from app.core.settings import settings
from app.core.utils.date_utils import utcnow
from app.domains.oauth.models import OAuthAuthorizationCode
from app.domains.oauth.services.oauth_service import is_allowed_redirect_uri, pkce_challenge
from app.domains.organization.models import Organization, OrganizationRole, OrganizationUser
from app.domains.user.models import User, UserToken
from app.main import app

AUTHORIZE = '/api/v1/oauth/authorize'
TOKEN = '/api/v1/oauth/token'
REVOKE = '/api/v1/oauth/revoke'
CLIENT_ID = 'hearfolio-app'
REDIRECT_URI = 'hearfolio://oauth/callback'


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    return verifier, pkce_challenge(verifier)


def _authorize_body(challenge: str, **overrides) -> dict:
    return {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'state': 'xyz',
        'device_name': 'MacBook Air',
        **overrides,
    }


def _app_client() -> AsyncClient:
    """The native app: no cookies, no Origin."""
    return AsyncClient(transport=ASGITransport(app=app), base_url=TEST_ORIGIN)


async def _authorize(api_client, auth_headers, user: User, **overrides) -> tuple[str, str]:
    verifier, challenge = _pkce()
    response = await api_client.post(
        AUTHORIZE, headers=await auth_headers(user), json=_authorize_body(challenge, **overrides)
    )
    assert response.status_code == 200, response.text
    return response.json()['code'], verifier


def _token_form(code: str, verifier: str, /, **overrides: str) -> dict:
    return {
        'grant_type': 'authorization_code',
        'code': code,
        'code_verifier': verifier,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        **overrides,
    }


# FULL FLOW


@pytest.mark.asyncio
async def test_full_flow_issues_named_api_token(api_client, user_factory, auth_headers):
    user = await user_factory()
    organization = await Organization.create(name='Acme', key='acme')
    await OrganizationUser.create(organization=organization, user=user, role=OrganizationRole.ADMIN)
    verifier, challenge = _pkce()

    response = await api_client.post(AUTHORIZE, headers=await auth_headers(user), json=_authorize_body(challenge))
    assert response.status_code == 200
    body = response.json()
    assert body['state'] == 'xyz'
    assert body['redirect_to'] == f'{REDIRECT_URI}?code={body["code"]}&state=xyz'
    stored = await OAuthAuthorizationCode.get(user=user)
    assert stored.code_hash == CryptoService.hash_value(body['code'])
    assert timedelta(seconds=55) < stored.expires_at - utcnow() <= timedelta(seconds=60)

    async with _app_client() as app_client:
        response = await app_client.post(TOKEN, data=_token_form(body['code'], verifier))
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'no-store'
        token = response.json()
        assert token['token_type'] == 'Token'
        assert token['user']['id'] == str(user.id)
        assert [(org['key'], org['role']) for org in token['organizations']] == [('acme', 'admin')]

        api_token = await UserToken.get(user=user)
        assert api_token.name == 'Hearfolio · MacBook Air'
        assert api_token.expires_at is None
        assert api_token.value_hash == CryptoService.hash_value(token['access_token'])

        headers = {'Authorization': f'Token {token["access_token"]}', 'Organization-Key': 'acme'}
        assert (await app_client.get('/api/v1/me/organizations', headers=headers)).status_code == 200
        assert (await app_client.post(REVOKE, headers=headers)).status_code == 204
        assert not await UserToken.exists(id=api_token.id)
        assert (await app_client.get('/api/v1/me/organizations', headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_token_endpoint_accepts_json_and_loopback_redirect(api_client, user_factory, auth_headers):
    user = await user_factory()
    redirect = 'http://127.0.0.1:53682/callback'
    code, verifier = await _authorize(api_client, auth_headers, user, redirect_uri=redirect)
    async with _app_client() as app_client:
        response = await app_client.post(TOKEN, json=_token_form(code, verifier, redirect_uri=redirect))
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_authorize_without_state(api_client, user_factory, auth_headers):
    user = await user_factory()
    _, challenge = _pkce()
    body = _authorize_body(challenge)
    del body['state']
    response = await api_client.post(AUTHORIZE, headers=await auth_headers(user), json=body)
    assert response.status_code == 200
    assert response.json()['redirect_to'] == f'{REDIRECT_URI}?code={response.json()["code"]}'


# TOKEN ERRORS


@pytest.mark.asyncio
async def test_wrong_verifier_is_invalid_grant_and_burns_the_code(api_client, user_factory, auth_headers):
    user = await user_factory()
    code, verifier = await _authorize(api_client, auth_headers, user)
    other_verifier, _ = _pkce()
    async with _app_client() as app_client:
        response = await app_client.post(TOKEN, data=_token_form(code, other_verifier))
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_grant'
        response = await app_client.post(TOKEN, data=_token_form(code, verifier))
        assert response.status_code == 400
    assert not await UserToken.exists(user=user)


@pytest.mark.asyncio
async def test_reused_code_revokes_the_issued_token(api_client, user_factory, auth_headers):
    user = await user_factory()
    code, verifier = await _authorize(api_client, auth_headers, user)
    async with _app_client() as app_client:
        first = await app_client.post(TOKEN, data=_token_form(code, verifier))
        assert first.status_code == 200
        second = await app_client.post(TOKEN, data=_token_form(code, verifier))
    assert second.status_code == 400
    assert second.json() == {'error': 'invalid_grant', 'error_description': 'Authorization code already used'}
    assert not await UserToken.exists(user=user)


@pytest.mark.asyncio
async def test_expired_code(api_client, user_factory, auth_headers):
    user = await user_factory()
    code, verifier = await _authorize(api_client, auth_headers, user)
    await OAuthAuthorizationCode.filter(user=user).update(expires_at=utcnow() - timedelta(seconds=1))
    async with _app_client() as app_client:
        response = await app_client.post(TOKEN, data=_token_form(code, verifier))
    assert response.status_code == 400
    assert response.json()['error'] == 'invalid_grant'
    assert not await UserToken.exists(user=user)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'overrides',
    [
        {'redirect_uri': 'http://127.0.0.1:9999/callback'},
        {'redirect_uri': 'hearfolio://oauth/callback/'},
    ],
)
async def test_redirect_uri_mismatch(api_client, user_factory, auth_headers, overrides):
    user = await user_factory()
    code, verifier = await _authorize(api_client, auth_headers, user)
    async with _app_client() as app_client:
        response = await app_client.post(TOKEN, data=_token_form(code, verifier, **overrides))
    assert response.status_code == 400
    assert response.json()['error'] == 'invalid_grant'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('overrides', 'error'),
    [
        ({'grant_type': 'password'}, 'unsupported_grant_type'),
        ({'grant_type': ''}, 'invalid_request'),
        ({'code_verifier': ''}, 'invalid_request'),
        ({'code_verifier': 'too-short'}, 'invalid_request'),
        ({'client_id': 'other-app'}, 'invalid_client'),
        ({'code': 'unknown-code'}, 'invalid_grant'),
    ],
)
async def test_token_request_errors(api_client, user_factory, auth_headers, overrides, error):
    user = await user_factory()
    code, verifier = await _authorize(api_client, auth_headers, user)
    async with _app_client() as app_client:
        response = await app_client.post(TOKEN, data=_token_form(code, verifier, **overrides))
    assert response.status_code == 400
    assert response.json()['error'] == error


@pytest.mark.asyncio
async def test_malformed_json_is_invalid_request(api_client):
    async with _app_client() as app_client:
        response = await app_client.post(TOKEN, content=b'[1, 2]', headers={'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert response.json()['error'] == 'invalid_request'


@pytest.mark.asyncio
async def test_inactive_user_cannot_redeem(api_client, user_factory, auth_headers):
    user = await user_factory()
    code, verifier = await _authorize(api_client, auth_headers, user)
    await User.filter(id=user.id).update(is_active=False)
    async with _app_client() as app_client:
        response = await app_client.post(TOKEN, data=_token_form(code, verifier))
    assert response.status_code == 400
    assert response.json()['error'] == 'invalid_grant'


@pytest.mark.asyncio
async def test_token_endpoint_is_rate_limited(api_client, monkeypatch):
    monkeypatch.setattr(settings, 'public_rate_limit_attempts', 2)
    async with _app_client() as app_client:
        for _ in range(2):
            response = await app_client.post(TOKEN, data=_token_form('nope', _pkce()[0]))
            assert response.status_code == 400
        response = await app_client.post(TOKEN, data=_token_form('nope', _pkce()[0]))
    assert response.status_code == 429
    assert response.json()['error'] == 'rate_limited'
    assert int(response.headers['retry-after']) > 0


# AUTHORIZE ERRORS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('overrides', 'error'),
    [
        ({'client_id': 'other-app'}, 'invalid_client'),
        ({'redirect_uri': 'https://evil.example/callback'}, 'invalid_request'),
        ({'redirect_uri': 'http://localhost:5000/callback'}, 'invalid_request'),
        ({'redirect_uri': 'http://127.0.0.1/callback'}, 'invalid_request'),
        ({'redirect_uri': 'http://127.0.0.1:5000/other'}, 'invalid_request'),
        ({'redirect_uri': 'hearfolio://oauth/callback?x=1'}, 'invalid_request'),
        ({'code_challenge_method': 'plain'}, 'invalid_request'),
        ({'code_challenge': 'short'}, 'invalid_request'),
        ({'device_name': '   '}, 'invalid_request'),
    ],
)
async def test_authorize_rejects_bad_requests(api_client, user_factory, auth_headers, overrides, error):
    user = await user_factory()
    _, challenge = _pkce()
    body = _authorize_body(challenge, **overrides)
    headers = await auth_headers(user)
    response = await api_client.post(AUTHORIZE, headers=headers, json=body)
    assert response.status_code == 400
    assert response.json()['error']['details']['error'] == error
    info = await api_client.get(AUTHORIZE, headers=headers, params=body)
    assert info.status_code == 400
    assert not await OAuthAuthorizationCode.exists()


@pytest.mark.asyncio
async def test_authorize_info_for_the_consent_screen(api_client, user_factory, auth_headers):
    user = await user_factory()
    _, challenge = _pkce()
    response = await api_client.get(
        AUTHORIZE, headers=await auth_headers(user), params=_authorize_body(challenge, device_name=' Pixel 9 ')
    )
    assert response.status_code == 200
    assert response.json() == {
        'client_id': CLIENT_ID,
        'client_name': 'Hearfolio',
        'redirect_uri': REDIRECT_URI,
        'device_name': 'Pixel 9',
    }


@pytest.mark.asyncio
async def test_authorize_requires_sign_in(api_client):
    _, challenge = _pkce()
    response = await api_client.post(AUTHORIZE, json=_authorize_body(challenge))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_authorize_with_cookie_needs_trusted_origin(api_client, user_factory):
    user = await user_factory()
    login = await api_client.post('/api/v1/auth/login', json={'email': user.email, 'password': TEST_PASSWORD})
    assert login.status_code == 200
    _, challenge = _pkce()
    response = await api_client.post(
        AUTHORIZE, json=_authorize_body(challenge), headers={'Origin': 'https://evil.example'}
    )
    assert response.status_code == 403
    assert not await OAuthAuthorizationCode.exists()
    response = await api_client.post(AUTHORIZE, json=_authorize_body(challenge))
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_api_token_cannot_authorize_another_app(api_client, user_factory, auth_headers):
    user = await user_factory()
    code, verifier = await _authorize(api_client, auth_headers, user)
    async with _app_client() as app_client:
        token = (await app_client.post(TOKEN, data=_token_form(code, verifier))).json()['access_token']
        _, challenge = _pkce()
        response = await app_client.post(
            AUTHORIZE, headers={'Authorization': f'Token {token}'}, json=_authorize_body(challenge)
        )
    assert response.status_code == 403


# REVOKE


@pytest.mark.asyncio
async def test_revoke_requires_an_api_token(api_client, user_factory, auth_headers):
    user = await user_factory()
    response = await api_client.post(REVOKE, headers=await auth_headers(user))
    assert response.status_code == 400
    assert response.json()['error'] == 'invalid_request'
    assert (await api_client.post(REVOKE)).status_code == 401


@pytest.mark.asyncio
async def test_revoke_deletes_only_the_calling_token(api_client, user_factory, auth_headers):
    user = await user_factory()
    tokens = []
    async with _app_client() as app_client:
        for _ in range(2):
            code, verifier = await _authorize(api_client, auth_headers, user)
            tokens.append((await app_client.post(TOKEN, data=_token_form(code, verifier))).json()['access_token'])
        assert (await app_client.post(REVOKE, headers={'Authorization': f'Token {tokens[0]}'})).status_code == 204
    remaining = await UserToken.filter(user=user).values_list('value_hash', flat=True)
    assert remaining == [CryptoService.hash_value(tokens[1])]


# REDIRECT URIS


@pytest.mark.parametrize(
    ('uri', 'allowed'),
    [
        ('hearfolio://oauth/callback', True),
        ('http://127.0.0.1:1/callback', True),
        ('http://127.0.0.1:65535/callback', True),
        ('http://127.0.0.1:65536/callback', False),
        ('http://127.0.0.1:0/callback', False),
        ('https://127.0.0.1:5000/callback', False),
        ('http://[::1]:5000/callback', False),
        ('http://127.0.0.1:5000/callback#x', False),
        ('http://user@127.0.0.1:5000/callback', False),
    ],
)
def test_allowed_redirect_uris(uri, allowed):
    assert is_allowed_redirect_uri(uri) is allowed


# WELL-KNOWN


@pytest.mark.asyncio
async def test_well_known_hearfolio(api_client, monkeypatch):
    monkeypatch.setattr(settings, 'public_url', 'https://rec.example.com')
    monkeypatch.setattr(settings, 'app_version', '1.2.3')
    monkeypatch.setattr(settings, 'recording_purge_after_days', 14)
    async with _app_client() as app_client:
        response = await app_client.get('/.well-known/hearfolio')
    assert response.status_code == 200
    assert response.json() == {
        'product': 'hearfolio',
        'name': settings.instance_name,
        'server_version': '1.2.3',
        'api_version': 1,
        'min_app_version': '0.10.0',
        'oauth': {
            'authorize_url': 'https://rec.example.com/oauth/authorize',
            'token_url': 'https://rec.example.com/api/v1/oauth/token',
            'revoke_url': 'https://rec.example.com/api/v1/oauth/revoke',
        },
        'upload': {
            'multipart_threshold_bytes': settings.upload_multipart_threshold_bytes,
            'part_size_bytes': settings.upload_part_size_bytes,
        },
        'recording_purge_after_days': 14,
    }


@pytest.mark.asyncio
async def test_well_known_falls_back_to_request_origin(api_client):
    response = await api_client.get('/.well-known/hearfolio')
    assert response.json()['oauth']['token_url'] == f'{TEST_ORIGIN}/api/v1/oauth/token'
