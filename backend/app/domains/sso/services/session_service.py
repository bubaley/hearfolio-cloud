"""
Sessions established through an organization's provider: creation, lazy revalidation, revocation and the «SSO only»
rule. See docs/sso.md («Сеансы и проверка у провайдера»).

Every authenticated request asks `guard()` whether its credential belongs to an SSO session (cached per process for
SSO_SESSION_CACHE_SECONDS, so plain password sessions cost one lookup per cache window). When the last successful
check is older than the organization's interval, one request (a database claim makes it one across processes)
re-checks the user at the provider: refresh token grant first, userinfo with the access token as fallback. A clear
"no" (`invalid_grant`, userinfo 401, rules no longer met) ends the session at once; an unreachable provider keeps it
working for SSO_REVALIDATE_GRACE_SECONDS since the last success.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, ClassVar
from uuid import UUID

from loguru import logger
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.services.crypto_service import CryptoService
from app.core.settings import settings
from app.core.utils.date_utils import as_utc, utcnow
from app.domains.auth.services.auth_service import Authentication, AuthMethod, AuthService
from app.domains.auth.services.token_service import TokenPair
from app.domains.organization.models import Organization
from app.domains.organization.services.organization_service import OrganizationService
from app.domains.sso.models import SsoIdentity, SsoLoginMode, SsoProvider, SsoSession, SsoSessionToken
from app.domains.sso.services.oidc_client import OidcClient, OidcError
from app.domains.sso.services.rules import SsoClaims, SsoRules
from app.domains.user.models import User, UserToken

# A check that started this long ago is considered dead; another request may claim the session.
CHECK_CLAIM_TIMEOUT = timedelta(seconds=60)
SSO_REQUIRED = 'Организация «{name}» открывается только после входа через SSO'


@dataclass(frozen=True)
class _Snapshot:
    session_id: UUID
    provider_id: UUID
    validated_at: datetime
    interval: timedelta
    revoked: bool


@dataclass(frozen=True)
class _OrganizationRule:
    provider_id: UUID
    sso_only: bool
    owner_password_fallback: bool


@dataclass(frozen=True)
class GuardResult:
    alive: bool
    session_id: UUID | None = None
    provider_id: UUID | None = None


NOT_SSO = GuardResult(alive=True)
ENDED = GuardResult(alive=False)


def encrypt_optional(value: Any) -> str:
    return CryptoService.encrypt(value) if isinstance(value, str) and value else ''


def decrypt_optional(value: str) -> str:
    return CryptoService.decrypt(value) if value else ''


def access_expiry(tokens: dict[str, Any]) -> datetime | None:
    expires_in = tokens.get('expires_in')
    if isinstance(expires_in, int | float) and not isinstance(expires_in, bool) and expires_in > 0:
        return utcnow() + timedelta(seconds=expires_in)
    return None


class SsoSessionService:
    _sessions: ClassVar[dict[tuple[str, UUID], tuple[float, _Snapshot | None]]] = {}
    _rules: ClassVar[dict[UUID, tuple[float, _OrganizationRule | None]]] = {}

    # CACHE

    @classmethod
    def clear_cache(cls) -> None:
        cls._sessions.clear()
        cls._rules.clear()

    @classmethod
    def forget_session(cls, session_id: UUID) -> None:
        for key, (_, snapshot) in list(cls._sessions.items()):
            if snapshot is not None and snapshot.session_id == session_id:
                cls._sessions.pop(key, None)

    @classmethod
    def forget_organization(cls, organization_id: UUID) -> None:
        cls._rules.pop(organization_id, None)

    @staticmethod
    def _fresh(stored_at: float) -> bool:
        return time.monotonic() - stored_at < settings.sso_session_cache_seconds

    # START

    @staticmethod
    async def start(user: User, identity: SsoIdentity, provider: SsoProvider, tokens: dict[str, Any]) -> TokenPair:
        """A Hearfolio session (cookies) marked as established through `provider`."""
        pair = await AuthService.start_session(user)
        await SsoSession.create(
            provider=provider,
            identity=identity,
            user=user,
            family_id=pair.session_id,
            refresh_token_encrypted=encrypt_optional(tokens.get('refresh_token')),
            access_token_encrypted=encrypt_optional(tokens.get('access_token')),
            access_token_expires_at=access_expiry(tokens),
            validated_at=utcnow(),
        )
        return pair

    @classmethod
    async def link_app_token(cls, family_id: UUID | None, token: UserToken) -> None:
        """An app token approved from an SSO session (OAuth consent) shares that session's fate."""
        if family_id is None:
            return
        session = await SsoSession.get_or_none(family_id=family_id, revoked_at=None)
        if session is not None:
            await SsoSessionToken.create(session=session, token=token)

    # GUARD (every authenticated request)

    @staticmethod
    def _key(authentication: Authentication) -> tuple[str, UUID] | None:
        if authentication.method == AuthMethod.API_TOKEN:
            return ('token', authentication.api_token_id) if authentication.api_token_id else None
        return ('family', authentication.session_id) if authentication.session_id else None

    @classmethod
    async def _load(cls, key: tuple[str, UUID]) -> _Snapshot | None:
        if key[0] == 'family':
            session = await SsoSession.filter(family_id=key[1]).select_related('provider').first()
        else:
            # Two queries: Tortoise mis-maps the nested select_related('session__provider') on PostgreSQL.
            link = await SsoSessionToken.get_or_none(token_id=key[1])
            session = await SsoSession.filter(id=link.session_id).select_related('provider').first() if link else None
        if session is None:
            return None
        return _Snapshot(
            session_id=session.id,
            provider_id=session.provider_id,
            validated_at=as_utc(session.validated_at),
            interval=timedelta(minutes=session.provider.revalidate_interval_minutes),
            revoked=session.revoked_at is not None,
        )

    @classmethod
    async def _snapshot(cls, key: tuple[str, UUID], *, reload: bool = False) -> _Snapshot | None:
        cached = cls._sessions.get(key)
        if cached and not reload and cls._fresh(cached[0]):
            return cached[1]
        snapshot = await cls._load(key)
        cls._sessions[key] = (time.monotonic(), snapshot)
        return snapshot

    @classmethod
    async def guard(cls, authentication: Authentication) -> GuardResult:
        """Is the credential's SSO session (if it is one) still alive? Revalidates at most once per interval."""
        key = cls._key(authentication)
        if key is None:
            return NOT_SSO
        return await cls._guard_key(key)

    @classmethod
    async def guard_family(cls, family_id: UUID | None) -> GuardResult:
        """The same check for a refresh-token rotation (`POST /auth/refresh`)."""
        return await cls._guard_key(('family', family_id)) if family_id else NOT_SSO

    @classmethod
    async def _guard_key(cls, key: tuple[str, UUID]) -> GuardResult:
        snapshot = await cls._snapshot(key)
        if snapshot is None:
            return NOT_SSO
        if not snapshot.revoked and utcnow() - snapshot.validated_at >= snapshot.interval:
            await cls._revalidate_due(snapshot)
            snapshot = await cls._snapshot(key, reload=True)
            if snapshot is None:
                return ENDED
        if snapshot.revoked:
            return ENDED
        return GuardResult(alive=True, session_id=snapshot.session_id, provider_id=snapshot.provider_id)

    @classmethod
    async def _revalidate_due(cls, snapshot: _Snapshot) -> None:
        now = utcnow()
        claimed = (
            await SsoSession.filter(id=snapshot.session_id, revoked_at=None, validated_at__lte=now - snapshot.interval)
            .filter(Q(check_started_at__isnull=True) | Q(check_started_at__lt=now - CHECK_CLAIM_TIMEOUT))
            .update(check_started_at=now)
        )
        if not claimed:
            # Another request checks it right now, or just did: use whatever the database says.
            return
        session = await SsoSession.get_or_none(id=snapshot.session_id)
        if session is None:
            return
        try:
            await cls.revalidate(session)
        finally:
            await SsoSession.filter(id=session.id).update(check_started_at=None)
            cls.forget_session(session.id)

    # REVALIDATION

    @classmethod
    async def revalidate(cls, session: SsoSession) -> bool:
        """Ask the provider whether the user is still allowed. False: the session was ended."""
        await session.fetch_related('provider', 'identity')
        provider: SsoProvider = session.provider
        identity: SsoIdentity = session.identity
        try:
            claims = await cls._check_with_provider(session, provider, identity)
        except OidcError as error:
            # invalid_client is our configuration (e.g. a rotated secret), not a verdict on the user.
            if error.transient or error.oauth_error == 'invalid_client':
                return await cls._provider_unavailable(session, error)
            logger.info('SSO session {} ended by the provider: {}', session.id, error.reason)
            await cls.revoke(session, error.reason)
            return False
        sso_claims = SsoClaims.from_claims(claims, fallback=identity)
        if not SsoRules.allows_access(provider, sso_claims):
            logger.info('SSO session {} ended: the organization rules are no longer met', session.id)
            await cls.revoke(session, 'rules_not_met')
            return False
        await SsoIdentity.filter(id=identity.id).update(
            email=sso_claims.email[:255],
            email_verified=sso_claims.email_verified,
            name=sso_claims.name[:255],
            groups=sso_claims.groups,
        )
        await SsoSession.filter(id=session.id, revoked_at=None).update(validated_at=utcnow())
        return True

    @staticmethod
    async def _check_with_provider(session: SsoSession, provider: SsoProvider, identity: SsoIdentity) -> dict[str, Any]:
        """
        Refresh token grant when there is a refresh token, then userinfo with the (new) access token. Runs only under
        the session's check claim, so a rotating refresh token is never presented twice; the rotated token is stored
        (compare-and-swap on the old ciphertext) before its result is used.
        """
        metadata = provider.metadata
        claims: dict[str, Any] = {}
        refresh_token = decrypt_optional(session.refresh_token_encrypted)
        access_token = decrypt_optional(session.access_token_encrypted)
        if refresh_token:
            tokens = await OidcClient.token_request(
                metadata,
                provider.client_id,
                CryptoService.decrypt(provider.client_secret_encrypted),
                {'grant_type': 'refresh_token', 'refresh_token': refresh_token},
            )
            access_token = tokens['access_token']
            stored = await SsoSession.filter(
                id=session.id, revoked_at=None, refresh_token_encrypted=session.refresh_token_encrypted
            ).update(
                refresh_token_encrypted=encrypt_optional(tokens.get('refresh_token') or refresh_token),
                access_token_encrypted=encrypt_optional(access_token),
                access_token_expires_at=access_expiry(tokens),
            )
            if not stored:
                # Ended (or changed) while we were asking: nothing to confirm any more.
                raise OidcError('session_changed', 'Сеанс изменился во время проверки')
            if isinstance(tokens.get('id_token'), str):
                claims = await OidcClient.validate_id_token(
                    metadata,
                    provider.client_id,
                    tokens['id_token'],
                    nonce=None,
                    expected_subject=identity.subject,
                    access_token=access_token,
                )
        elif session.access_token_expires_at is not None and as_utc(session.access_token_expires_at) <= utcnow():
            # No refresh token (no offline_access) and the access token ran out: the provider cannot be asked. Not a
            # verdict on the user: the grace period applies, then they sign in again.
            raise OidcError('reauth_required', 'Сеанс у провайдера истёк: войдите снова', transient=True)
        if not access_token:
            raise OidcError('reauth_required', 'Провайдер не выдал токены для проверки сеанса', transient=True)
        if metadata.get('userinfo_endpoint'):
            info = await OidcClient.userinfo(metadata, access_token)
            if info.get('sub') != identity.subject:
                raise OidcError('subject_mismatch', 'Провайдер вернул другого пользователя')
            claims = {**claims, **info}
        elif not refresh_token:
            # Neither a refresh token nor userinfo: nothing can confirm the user any more.
            raise OidcError('reauth_required', 'Сеанс нельзя проверить у провайдера: войдите снова', transient=True)
        return claims

    @classmethod
    async def _provider_unavailable(cls, session: SsoSession, error: OidcError) -> bool:
        if utcnow() - as_utc(session.validated_at) > timedelta(seconds=settings.sso_revalidate_grace_seconds):
            logger.warning('SSO session {} ended: provider unavailable past the grace period ({})', session.id, error)
            await cls.revoke(
                session, 'reauth_required' if error.reason == 'reauth_required' else 'provider_unavailable'
            )
            return False
        logger.warning('SSO session {} kept: provider unavailable ({})', session.id, error)
        return True

    # REVOCATION

    @classmethod
    async def revoke(cls, session: SsoSession, reason: str) -> None:
        """End the session everywhere: its refresh-token family, the app tokens approved from it, its cache entry."""
        async with in_transaction():
            # Wipe the stored provider tokens; empty strings are not credentials.
            await SsoSession.filter(id=session.id, revoked_at=None).update(
                revoked_at=utcnow(),
                revoke_reason=reason[:32],
                refresh_token_encrypted='',  # nosec B106
                access_token_encrypted='',  # nosec B106
            )
            await AuthService.revoke_family(session.family_id)
            token_ids = await SsoSessionToken.filter(session_id=session.id).values_list('token_id', flat=True)
            if token_ids:
                await UserToken.filter(id__in=list(token_ids)).delete()
        cls.forget_session(session.id)

    @classmethod
    async def revoke_where(cls, reason: str, **filters: Any) -> int:
        sessions = await SsoSession.filter(revoked_at=None, **filters)
        for session in sessions:
            await cls.revoke(session, reason)
        return len(sessions)

    @classmethod
    async def end_family(cls, family_id: UUID | None) -> None:
        """Sign-out of a web session: its SSO session (if any) ends too."""
        if family_id is not None:
            await cls.revoke_where('logout', family_id=family_id)

    # «SSO ONLY»

    @classmethod
    async def _organization_rule(cls, organization_id: UUID) -> _OrganizationRule | None:
        cached = cls._rules.get(organization_id)
        if cached and cls._fresh(cached[0]):
            return cached[1]
        provider = await SsoProvider.get_or_none(organization_id=organization_id)
        rule = (
            _OrganizationRule(
                provider_id=provider.id,
                sso_only=provider.login_mode == SsoLoginMode.SSO_ONLY,
                owner_password_fallback=provider.owner_password_fallback,
            )
            if provider
            else None
        )
        cls._rules[organization_id] = (time.monotonic(), rule)
        return rule

    @classmethod
    async def enforce(cls, user: User, organization: Organization, sso_provider_id: UUID | None) -> None:
        """403 `sso_required` when the organization is «SSO only» and this session did not come through its provider."""
        rule = await cls._organization_rule(organization.id)
        if rule is None or not rule.sso_only or sso_provider_id == rule.provider_id or user.is_superuser:
            return
        if rule.owner_password_fallback and await OrganizationService.is_owner(user, organization.id):
            return
        raise AppException.from_attrs(
            ErrorCode.FORBIDDEN,
            SSO_REQUIRED.format(name=organization.name),
            details={'reason': 'sso_required', 'organization_key': organization.key},
        )
