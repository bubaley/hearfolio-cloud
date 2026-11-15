"""
A fake OpenID Connect provider behind `httpx2.MockTransport`: discovery, JWKS (RSA keys generated per test), token
(authorization_code + PKCE, refresh_token with rotation) and userinfo. Tests drive the real Hearfolio endpoints.
"""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core.settings import settings
from app.domains.organization.models import Organization, OrganizationRole, OrganizationUser
from app.domains.sso.models import SsoProvider
from app.domains.sso.services.oidc_client import OidcClient, at_hash
from app.domains.sso.services.session_service import SsoSessionService
from app.domains.user.models import User

ISSUER = 'https://idp.example.com/api/v1/oidc'
CLIENT_ID = 'hearfolio-client'
CLIENT_SECRET = 'client-secret-value-0123456789'


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class FakeUser:
    sub: str
    email: str
    email_verified: bool = True
    name: str = 'Иван Петров'
    groups: list[str] = field(default_factory=list)
    active: bool = True


@dataclass
class FakeIdP:
    key: rsa.RSAPrivateKey = field(default_factory=_new_key)
    kid: str = 'key-1'
    users: dict[str, FakeUser] = field(default_factory=dict)
    codes: dict[str, dict[str, Any]] = field(default_factory=dict)
    refresh_tokens: dict[str, str] = field(default_factory=dict)
    # Rotated refresh tokens: presenting one again revokes everything of that user (strict reuse detection).
    used_refresh_tokens: dict[str, str] = field(default_factory=dict)
    access_ttl: int = 900
    access_tokens: dict[str, str] = field(default_factory=dict)
    # Failure switches
    down: bool = False
    issue_refresh_tokens: bool = True
    id_token_overrides: dict[str, Any] = field(default_factory=dict)
    signing_key: rsa.RSAPrivateKey | None = None
    calls: list[str] = field(default_factory=list)

    def add_user(self, **kwargs: Any) -> FakeUser:
        user = FakeUser(**kwargs)
        self.users[user.sub] = user
        return user

    # The user signs in at the provider and approves: the provider redirects back with a code.
    def authorize(self, authorization_url: str, sub: str) -> tuple[str, dict[str, str]]:
        params = {key: values[0] for key, values in parse_qs(urlsplit(authorization_url).query).items()}
        code = secrets.token_urlsafe(16)
        self.codes[code] = {**params, 'sub': sub}
        return code, params

    def discovery(self) -> dict[str, Any]:
        return {
            'issuer': ISSUER,
            'authorization_endpoint': f'{ISSUER}/authorize',
            'token_endpoint': f'{ISSUER}/token',
            'userinfo_endpoint': f'{ISSUER}/userinfo',
            'jwks_uri': f'{ISSUER}/jwks',
            'scopes_supported': ['openid', 'email', 'profile', 'groups', 'offline_access'],
            'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code', 'refresh_token'],
            'subject_types_supported': ['public'],
            'id_token_signing_alg_values_supported': ['RS256'],
            'token_endpoint_auth_methods_supported': ['client_secret_basic', 'client_secret_post'],
            'code_challenge_methods_supported': ['S256'],
        }

    def id_token(self, user: FakeUser, nonce: str | None, access_token: str | None = None) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            'iss': ISSUER,
            'sub': user.sub,
            'aud': CLIENT_ID,
            'iat': now,
            'exp': now + 300,
            'auth_time': now,
            'email': user.email,
            'email_verified': user.email_verified,
            'name': user.name,
            'groups': user.groups,
        }
        if nonce is not None:
            claims['nonce'] = nonce
        if access_token is not None:
            claims['at_hash'] = at_hash(access_token, 'RS256')
        claims.update(self.id_token_overrides)
        return jwt.encode(claims, self.signing_key or self.key, algorithm='RS256', headers={'kid': self.kid})

    def _tokens(self, user: FakeUser, nonce: str | None) -> dict[str, Any]:
        access = secrets.token_urlsafe(16)
        self.access_tokens[access] = user.sub
        body: dict[str, Any] = {
            'access_token': access,
            'token_type': 'Bearer',
            'expires_in': self.access_ttl,
            'id_token': self.id_token(user, nonce, access),
        }
        if self.issue_refresh_tokens:
            refresh = secrets.token_urlsafe(16)
            self.refresh_tokens[refresh] = user.sub
            body['refresh_token'] = refresh
        return body

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        self.calls.append(f'{request.method} {path}')
        if self.down:
            return httpx2.Response(503, json={'error': 'temporarily_unavailable'})
        if path == '/api/v1/oidc/.well-known/openid-configuration':
            return httpx2.Response(200, json=self.discovery())
        if path == '/api/v1/oidc/jwks':
            jwk = RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
            return httpx2.Response(200, json={'keys': [{**jwk, 'kid': self.kid, 'use': 'sig', 'alg': 'RS256'}]})
        if path == '/api/v1/oidc/token':
            return self._token(request)
        if path == '/api/v1/oidc/userinfo':
            token = request.headers.get('authorization', '').removeprefix('Bearer ')
            user = self.users.get(self.access_tokens.get(token, ''))
            if user is None or not user.active:
                return httpx2.Response(401, json={'error': 'invalid_token'})
            return httpx2.Response(
                200,
                json={
                    'sub': user.sub,
                    'email': user.email,
                    'email_verified': user.email_verified,
                    'name': user.name,
                    'groups': user.groups,
                },
            )
        return httpx2.Response(404)

    def _token(self, request: httpx2.Request) -> httpx2.Response:
        expected = base64.b64encode(f'{CLIENT_ID}:{CLIENT_SECRET}'.encode()).decode()
        if request.headers.get('authorization') != f'Basic {expected}':
            return httpx2.Response(401, json={'error': 'invalid_client'})
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if form.get('grant_type') == 'authorization_code':
            pending = self.codes.pop(form.get('code', ''), None)
            if pending is None or pending['redirect_uri'] != form.get('redirect_uri'):
                return httpx2.Response(400, json={'error': 'invalid_grant'})
            verifier = form.get('code_verifier', '')
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            if challenge != pending['code_challenge']:
                return httpx2.Response(400, json={'error': 'invalid_grant'})
            return httpx2.Response(200, json=self._tokens(self.users[pending['sub']], pending['nonce']))
        if form.get('grant_type') == 'refresh_token':
            presented = form.get('refresh_token', '')
            if presented in self.used_refresh_tokens:
                reused_sub = self.used_refresh_tokens[presented]
                for token, owner in list(self.refresh_tokens.items()):
                    if owner == reused_sub:
                        del self.refresh_tokens[token]
                return httpx2.Response(400, json={'error': 'invalid_grant', 'error_description': 'reuse'})
            sub = self.refresh_tokens.pop(presented, None)
            if sub is not None:
                self.used_refresh_tokens[presented] = sub
            user = self.users.get(sub or '')
            if user is None or not user.active:
                return httpx2.Response(400, json={'error': 'invalid_grant'})
            body = self._tokens(user, None)
            return httpx2.Response(200, json=body)
        return httpx2.Response(400, json={'error': 'unsupported_grant_type'})


@pytest.fixture
def idp(monkeypatch: pytest.MonkeyPatch) -> FakeIdP:
    fake = FakeIdP()
    monkeypatch.setattr(OidcClient, 'transport', httpx2.MockTransport(fake.handler))

    async def public_host(host: str) -> list[str]:
        return ['93.184.216.34']

    monkeypatch.setattr(OidcClient, 'lookup_host', staticmethod(public_host))
    monkeypatch.setattr(OidcClient, '_jwks_cache', {})
    monkeypatch.setattr(settings, 'sso_session_cache_seconds', 0.0)
    SsoSessionService.clear_cache()
    return fake


@pytest.fixture
def sso_org(db, idp, organization_factory, user_factory):
    """An organization with an owner and the fake provider connected (password + SSO, invite only)."""

    async def build(**rules: Any) -> tuple[Organization, User, SsoProvider]:
        owner = await user_factory()
        organization = await organization_factory()
        await OrganizationUser.create(organization=organization, user=owner, role=OrganizationRole.OWNER)
        from app.core.services.crypto_service import CryptoService

        provider = await SsoProvider.create(
            organization=organization,
            issuer=ISSUER,
            client_id=CLIENT_ID,
            client_secret_encrypted=CryptoService.encrypt(CLIENT_SECRET),
            scopes=['openid', 'email', 'profile', 'groups', 'offline_access'],
            button_label='Войти через Example',
            metadata=idp.discovery(),
            **rules,
        )
        return organization, owner, provider

    return build


async def sso_sign_in(api_client: httpx2.AsyncClient, idp: FakeIdP, organization_key: str, sub: str, **start: Any):
    """Start at Hearfolio, «sign in» at the provider, follow the callback. Returns the callback response."""
    started = await api_client.post('/api/v1/sso/start', json={'organization_key': organization_key, **start})
    assert started.status_code == 200, started.text
    code, params = idp.authorize(started.json()['authorization_url'], sub)
    callback = urlsplit(params['redirect_uri'])
    return await api_client.get(callback.path, params={'code': code, 'state': params['state']})
