import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from urllib.parse import urlencode
from uuid import UUID

from loguru import logger
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.services.crypto_service import CryptoService
from app.core.services.rate_limiter import oauth_rate_limiter
from app.core.utils.date_utils import as_utc, utcnow
from app.domains.auth.services.auth_service import AuthMethod
from app.domains.oauth.models import OAuthAuthorizationCode
from app.domains.oauth.schemas import OAuthAuthorizeInfoSchema, OAuthAuthorizeRequest, OAuthTokenRequest
from app.domains.user.models import User, UserToken
from app.domains.user.services.user_service import UserService

CODE_TTL = timedelta(seconds=60)
CODE_RETENTION = timedelta(days=1)
TOKEN_NAME = 'Hearfolio · {device_name}'
APP_REDIRECT_URI = 'hearfolio://oauth/callback'
# RFC 8252 §7.3: loopback redirect on any port; only the IPv4 literal, never `localhost`.
LOOPBACK_REDIRECT_URI = re.compile(r'^http://127\.0\.0\.1:(\d{1,5})/callback$')
# base64url(SHA-256(verifier)) without padding is always 43 characters.
CODE_CHALLENGE = re.compile(r'^[A-Za-z0-9_-]{43}$')
CODE_VERIFIER = re.compile(r'^[A-Za-z0-9._~-]{43,128}$')


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    name: str


# Public clients (no secret): PKCE proves the code is redeemed by the app that requested it.
OAUTH_CLIENTS = {client.client_id: client for client in (OAuthClient(client_id='hearfolio-app', name='Hearfolio'),)}


class OAuthErrorCode(StrEnum):
    INVALID_REQUEST = 'invalid_request'
    INVALID_CLIENT = 'invalid_client'
    INVALID_GRANT = 'invalid_grant'
    UNSUPPORTED_GRANT_TYPE = 'unsupported_grant_type'
    RATE_LIMITED = 'rate_limited'


class OAuthError(Exception):
    """An RFC 6749 §5.2 error of the token/revoke endpoints; the view renders `{error, error_description}`."""

    def __init__(
        self, error: OAuthErrorCode, description: str, status_code: int = 400, headers: dict[str, str] | None = None
    ):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code
        self.headers = headers


def _authorize_error(error: OAuthErrorCode, description: str) -> AppException:
    # The authorize endpoint serves the web app's consent page, so it keeps the API error envelope.
    return AppException.from_attrs(ErrorCode.VALIDATION_ERROR, description, details={'error': str(error)})


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def is_allowed_redirect_uri(redirect_uri: str) -> bool:
    if redirect_uri == APP_REDIRECT_URI:
        return True
    match = LOOPBACK_REDIRECT_URI.match(redirect_uri)
    return bool(match) and 0 < int(match.group(1)) <= 65535


class OAuthService:
    """
    Authorization code + PKCE (S256) for the Hearfolio apps:

    - authorize: a signed-in user approves the app; a single-use code valid 60 s is stored hashed and bound to
      user, client, redirect URI, code challenge and device name
    - exchange: the app redeems the code with its verifier for a regular named API token
    - revoke: the app deletes the API token it authenticates with
    """

    # AUTHORIZE

    @staticmethod
    def validate_authorization(data: OAuthAuthorizeRequest, auth_method: AuthMethod | None) -> OAuthAuthorizeInfoSchema:
        if auth_method == AuthMethod.API_TOKEN:
            raise AppException.from_attrs(ErrorCode.FORBIDDEN, 'API tokens cannot authorize apps')
        client = OAUTH_CLIENTS.get(data.client_id)
        if client is None:
            raise _authorize_error(OAuthErrorCode.INVALID_CLIENT, 'Unknown client')
        if not is_allowed_redirect_uri(data.redirect_uri):
            raise _authorize_error(OAuthErrorCode.INVALID_REQUEST, 'redirect_uri is not allowed for this client')
        if data.response_type is not None and data.response_type != 'code':
            raise _authorize_error(OAuthErrorCode.INVALID_REQUEST, 'response_type must be code')
        if data.code_challenge_method != 'S256':
            raise _authorize_error(OAuthErrorCode.INVALID_REQUEST, 'code_challenge_method must be S256')
        if not CODE_CHALLENGE.match(data.code_challenge):
            raise _authorize_error(OAuthErrorCode.INVALID_REQUEST, 'code_challenge must be a base64url SHA-256')
        device_name = data.device_name.strip()
        if not device_name:
            raise _authorize_error(OAuthErrorCode.INVALID_REQUEST, 'device_name is required')
        return OAuthAuthorizeInfoSchema(
            client_id=client.client_id,
            client_name=client.name,
            redirect_uri=data.redirect_uri,
            device_name=device_name,
        )

    @staticmethod
    async def authorize(user: User, data: OAuthAuthorizeRequest, info: OAuthAuthorizeInfoSchema) -> tuple[str, str]:
        """Return the code and the URL to redirect the browser to."""
        code = secrets.token_urlsafe(32)
        await OAuthAuthorizationCode.create(
            user=user,
            code_hash=CryptoService.hash_value(code),
            client_id=info.client_id,
            redirect_uri=info.redirect_uri,
            code_challenge=data.code_challenge,
            device_name=info.device_name,
            expires_at=utcnow() + CODE_TTL,
        )
        params = {'code': code, **({'state': data.state} if data.state is not None else {})}
        return code, f'{info.redirect_uri}?{urlencode(params)}'

    # TOKEN

    @staticmethod
    async def exchange(data: OAuthTokenRequest, client_ip: str) -> tuple[User, str]:
        """Redeem a code for a new API token. Failed grants count towards the per-IP limit."""
        if retry_after := await oauth_rate_limiter.retry_after(client_ip):
            raise OAuthError(
                OAuthErrorCode.RATE_LIMITED,
                'Too many attempts',
                status_code=429,
                headers={'Retry-After': str(retry_after)},
            )
        try:
            return await OAuthService._exchange(data)
        except OAuthError:
            await oauth_rate_limiter.hit(client_ip)
            raise

    @staticmethod
    async def _exchange(data: OAuthTokenRequest) -> tuple[User, str]:
        if not data.grant_type:
            raise OAuthError(OAuthErrorCode.INVALID_REQUEST, 'grant_type is required')
        if data.grant_type != 'authorization_code':
            raise OAuthError(OAuthErrorCode.UNSUPPORTED_GRANT_TYPE, 'Only authorization_code is supported')
        raw_code, verifier, client_id, redirect_uri = data.code, data.code_verifier, data.client_id, data.redirect_uri
        if not (raw_code and verifier and client_id and redirect_uri):
            missing = [
                name for name in ('code', 'code_verifier', 'redirect_uri', 'client_id') if not getattr(data, name)
            ]
            raise OAuthError(OAuthErrorCode.INVALID_REQUEST, f'Missing: {", ".join(missing)}')
        if client_id not in OAUTH_CLIENTS:
            raise OAuthError(OAuthErrorCode.INVALID_CLIENT, 'Unknown client')
        if not CODE_VERIFIER.match(verifier):
            raise OAuthError(OAuthErrorCode.INVALID_REQUEST, 'code_verifier is malformed')

        user, value, error = await OAuthService._redeem(
            CryptoService.hash_value(raw_code), verifier, client_id, redirect_uri
        )
        if error is not None or user is None or value is None:
            raise error or OAuthError(OAuthErrorCode.INVALID_GRANT, 'Invalid authorization code')
        return user, value

    @staticmethod
    async def _redeem(
        code_hash: str, verifier: str, client_id: str, redirect_uri: str
    ) -> tuple[User | None, str | None, OAuthError | None]:
        """
        Claim the code and issue its token in one transaction with the code row locked, so a concurrent reuse waits
        until `token_id` is set and then revokes that token (RFC 6749 §4.1.2). Errors are returned, not raised:
        raising would roll back the claim (a failed attempt must still burn the code) and the reuse revocation.
        """
        now = utcnow()
        async with in_transaction():
            code = await OAuthAuthorizationCode.filter(code_hash=code_hash).select_for_update().first()
            if code is None:
                return None, None, OAuthError(OAuthErrorCode.INVALID_GRANT, 'Invalid authorization code')
            if code.used_at is not None:
                if code.token_id:
                    await UserToken.filter(id=code.token_id).delete()
                logger.warning('OAuth code reuse for user {}: issued token revoked', code.user_id)
                return None, None, OAuthError(OAuthErrorCode.INVALID_GRANT, 'Authorization code already used')
            # Claim first: whatever happens next, a code is redeemed at most once.
            code.used_at = now
            await code.save(update_fields=['used_at', 'updated_at'])
            error = OAuthService._check_code(code, verifier, client_id, redirect_uri, now)
            if error is not None:
                return None, None, error
            user = await User.get_or_none(id=code.user_id, is_active=True)
            if user is None:
                return None, None, OAuthError(OAuthErrorCode.INVALID_GRANT, 'User is not active')
            token, value = await UserService.create_api_token(
                user.id, TOKEN_NAME.format(device_name=code.device_name), expires_at=None
            )
            code.token_id = token.id
            await code.save(update_fields=['token_id', 'updated_at'])
        return user, value, None

    @staticmethod
    def _check_code(
        code: OAuthAuthorizationCode, verifier: str, client_id: str, redirect_uri: str, now: datetime
    ) -> OAuthError | None:
        if as_utc(code.expires_at) <= now:
            return OAuthError(OAuthErrorCode.INVALID_GRANT, 'Authorization code expired')
        if code.client_id != client_id or code.redirect_uri != redirect_uri:
            return OAuthError(OAuthErrorCode.INVALID_GRANT, 'client_id or redirect_uri does not match the request')
        if not hmac.compare_digest(pkce_challenge(verifier), code.code_challenge):
            return OAuthError(OAuthErrorCode.INVALID_GRANT, 'code_verifier does not match')
        return None

    # CLEANUP

    @staticmethod
    async def purge_expired_codes() -> int:
        """Periodic: codes expired over a day ago (kept that long so a late reuse still revokes its token)."""
        return await OAuthAuthorizationCode.filter(expires_at__lt=utcnow() - CODE_RETENTION).delete()

    # REVOKE

    @staticmethod
    async def revoke(user: User, auth_method: AuthMethod | None, api_token_id: UUID | None) -> None:
        """Delete the API token the request is authenticated with (the app signing out)."""
        if auth_method != AuthMethod.API_TOKEN or api_token_id is None:
            raise OAuthError(OAuthErrorCode.INVALID_REQUEST, 'Authenticate with the API token to revoke')
        await UserToken.filter(id=api_token_id, user_id=user.id).delete()
