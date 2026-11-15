"""
Sign-in through an organization's provider: Authorization Code + PKCE (S256) with `state` and `nonce`.

`start` stores the pending request server-side (state as SHA-256, nonce, encrypted PKCE verifier) bound to the
browser by an HttpOnly cookie; `callback` checks state + browser, exchanges the code, validates the ID token (JWKS,
iss, aud, exp, nonce), reads userinfo, then links or creates the user per the organization's rules and starts a
session marked with the provider. Linking goes by `sub`; a first link to an existing account needs `email_verified`.
"""

import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from loguru import logger
from pydantic import TypeAdapter, ValidationError
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.fields.email_field import NormalizedEmail
from app.core.schemas import ErrorCode
from app.core.services.crypto_service import CryptoService
from app.core.settings import settings
from app.core.utils.date_utils import utcnow
from app.domains.auth.services.token_service import TokenPair
from app.domains.oauth.services.oauth_service import pkce_challenge
from app.domains.organization.models import Organization, OrganizationRole, OrganizationUser
from app.domains.sso.models import SsoIdentity, SsoLoginIntent, SsoLoginRequest, SsoProvider
from app.domains.sso.services.oidc_client import OidcClient, OidcError
from app.domains.sso.services.rules import SsoClaims, SsoRules
from app.domains.sso.services.session_service import SsoSessionService
from app.domains.user.models import User

CALLBACK_PATH = '/api/v1/sso/callback/{organization_id}'
LOGIN_PAGE_PATH = '/sso/{key}'
DEFAULT_REDIRECT = '/home'
PROFILE_REDIRECT = '/settings/profile'
LOGIN_REQUEST_RETENTION = timedelta(days=1)
_email_adapter: TypeAdapter[str] = TypeAdapter(NormalizedEmail)


def safe_redirect(value: str | None, default: str = DEFAULT_REDIRECT) -> str:
    """Same-site paths only (`/oauth/authorize?...`), never `//host`, a full URL or the API itself."""
    if not value or not value.startswith('/') or value.startswith('//') or '\\' in value:
        return default
    if value.startswith('/api/') or any(ord(char) < 32 for char in value):
        return default
    return value


def _not_configured(label: str) -> AppException:
    return AppException.from_attrs(
        ErrorCode.NOT_FOUND, f'Для {label} вход через SSO не настроен', details={'reason': 'sso_not_configured'}
    )


@dataclass(frozen=True)
class CallbackParams:
    code: str | None
    state: str | None
    error: str | None
    iss: str | None


@dataclass(frozen=True)
class CallbackResult:
    """Where the browser goes next; `tokens` when a session was started (set the cookies)."""

    redirect_to: str
    intent: SsoLoginIntent
    organization: Organization
    tokens: TokenPair | None = None


class SsoLoginService:
    # URLS

    @staticmethod
    def redirect_uri(base_url: str, organization_id: UUID) -> str:
        return base_url + CALLBACK_PATH.format(organization_id=organization_id)

    @staticmethod
    def login_url(base_url: str, organization_key: str) -> str:
        return base_url + LOGIN_PAGE_PATH.format(key=organization_key)

    # PROVIDER LOOKUP

    @staticmethod
    async def provider_by_key(key: str) -> SsoProvider:
        provider = await SsoProvider.filter(organization__key=key).select_related('organization').first()
        if provider is None:
            raise _not_configured(f'организации «{key}»')
        return provider

    @classmethod
    async def provider_by_email(cls, email: str) -> SsoProvider:
        domain = email.strip().lower().rpartition('@')[2]
        if not domain:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Укажите рабочую почту или ключ организации')
        providers = [
            provider
            for provider in await SsoProvider.all().select_related('organization')
            if domain in (provider.allowed_email_domains or [])
        ]
        if not providers:
            raise _not_configured(f'домена {domain}')
        if len(providers) > 1:
            raise AppException.from_attrs(
                ErrorCode.VALIDATION_ERROR,
                f'Домен {domain} используется в нескольких организациях. Укажите ключ организации',
                details={'reason': 'ambiguous_domain'},
            )
        return providers[0]

    # START

    @classmethod
    async def start(
        cls,
        provider: SsoProvider,
        *,
        base_url: str,
        browser_token: str | None,
        intent: SsoLoginIntent = SsoLoginIntent.LOGIN,
        user: User | None = None,
        redirect: str | None = None,
        login_hint: str | None = None,
    ) -> tuple[str, str]:
        """The provider authorization URL and the browser-binding value for the HttpOnly cookie."""
        metadata = provider.metadata or {}
        endpoint = metadata.get('authorization_endpoint')
        if not endpoint:
            raise AppException.from_attrs(
                ErrorCode.VALIDATION_ERROR, 'Провайдер подключён не до конца: проверьте подключение в настройках'
            )
        # One binding value per browser, so sign-ins started in parallel tabs all stay valid.
        browser_token = browser_token if browser_token and len(browser_token) >= 32 else secrets.token_urlsafe(32)
        state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        default_redirect = PROFILE_REDIRECT if intent == SsoLoginIntent.LINK else DEFAULT_REDIRECT
        await SsoLoginRequest.create(
            provider=provider,
            state_hash=CryptoService.hash_value(state),
            browser_hash=CryptoService.hash_value(browser_token),
            nonce=nonce,
            code_verifier_encrypted=CryptoService.encrypt(verifier),
            intent=intent,
            user=user,
            redirect_path=safe_redirect(redirect, default_redirect),
            expires_at=utcnow() + timedelta(seconds=settings.sso_login_request_ttl_seconds),
        )
        params = {
            'response_type': 'code',
            'client_id': provider.client_id,
            'redirect_uri': cls.redirect_uri(base_url, provider.organization_id),
            'scope': ' '.join(provider.scopes or ['openid']),
            'state': state,
            'nonce': nonce,
            'code_challenge': pkce_challenge(verifier),
            'code_challenge_method': 'S256',
        }
        if login_hint:
            params['login_hint'] = login_hint
        separator = '&' if '?' in endpoint else '?'
        return f'{endpoint}{separator}{urlencode(params)}', browser_token

    # CALLBACK

    @classmethod
    async def _claim_request(
        cls, organization_id: UUID, state: str | None, browser_token: str | None
    ) -> SsoLoginRequest:
        expired = OidcError('invalid_state', 'Вход устарел или уже завершён. Начните заново')
        if not state:
            raise expired
        request = (
            await SsoLoginRequest.filter(state_hash=CryptoService.hash_value(state))
            .select_related('provider__organization', 'user')
            .first()
        )
        if request is None or request.provider.organization_id != organization_id:
            raise expired
        now = utcnow()
        claimed = await SsoLoginRequest.filter(id=request.id, used_at=None, expires_at__gt=now).update(used_at=now)
        if not claimed:
            raise expired
        if not browser_token or not hmac.compare_digest(CryptoService.hash_value(browser_token), request.browser_hash):
            raise OidcError('browser_mismatch', 'Вход начат в другом браузере. Начните заново в этом')
        return request

    @classmethod
    async def callback(
        cls, organization_id: UUID, params: CallbackParams, *, base_url: str, browser_token: str | None
    ) -> CallbackResult:
        request = await cls._claim_request(organization_id, params.state, browser_token)
        provider: SsoProvider = request.provider
        organization: Organization = provider.organization
        if params.error:
            reason = 'provider_denied' if params.error == 'access_denied' else 'provider_error'
            raise OidcError(reason, 'Провайдер не подтвердил вход')
        metadata = provider.metadata or {}
        # RFC 9207: a provider that names itself in the response must be the one this sign-in went to.
        if params.iss is not None and params.iss != metadata.get('issuer'):
            raise OidcError('invalid_issuer', 'Ответ пришёл от другого провайдера')
        if not params.code:
            raise OidcError('invalid_request', 'Провайдер не вернул код входа')

        tokens = await OidcClient.token_request(
            metadata,
            provider.client_id,
            CryptoService.decrypt(provider.client_secret_encrypted),
            {
                'grant_type': 'authorization_code',
                'code': params.code,
                'redirect_uri': cls.redirect_uri(base_url, organization_id),
                'code_verifier': CryptoService.decrypt(request.code_verifier_encrypted),
            },
        )
        if not isinstance(tokens.get('id_token'), str):
            raise OidcError('invalid_id_token', 'Провайдер не вернул ID-токен: проверьте, что запрошен scope openid')
        claims: dict[str, Any] = await OidcClient.validate_id_token(
            metadata, provider.client_id, tokens['id_token'], nonce=request.nonce, access_token=tokens['access_token']
        )
        if metadata.get('userinfo_endpoint'):
            info = await OidcClient.userinfo(metadata, tokens['access_token'])
            if info.get('sub') != claims['sub']:
                raise OidcError('subject_mismatch', 'Провайдер вернул другого пользователя')
            claims = {**claims, **info}
        sso_claims = SsoClaims.from_claims(claims)

        if request.intent == SsoLoginIntent.LINK:
            return await cls._link(request, provider, organization, sso_claims, tokens)
        return await cls._login(request, provider, organization, sso_claims, tokens)

    # LOGIN

    @classmethod
    async def _login(
        cls,
        request: SsoLoginRequest,
        provider: SsoProvider,
        organization: Organization,
        claims: SsoClaims,
        tokens: dict[str, Any],
    ) -> CallbackResult:
        identity = await SsoIdentity.filter(provider=provider, subject=claims.subject).select_related('user').first()
        user: User | None = identity.user if identity else await cls._existing_user(provider, claims)
        if user is not None and not user.is_active:
            raise OidcError('user_inactive', 'Аккаунт отключён. Обратитесь к администратору')
        cls._check_rules(provider, claims)
        is_member = user is not None and await OrganizationUser.exists(organization=organization, user=user)
        if not is_member and not SsoRules.allows_join(provider, claims):
            raise OidcError(
                'not_member',
                f'Вы не участник организации «{organization.name}». Попросите приглашение у администратора',
            )

        async with in_transaction():
            created_user = False
            if user is None:
                user = await cls._create_user(claims)
                created_user = True
            if not is_member:
                role = (
                    provider.default_role
                    if provider.default_role != OrganizationRole.OWNER
                    else OrganizationRole.MEMBER
                )
                try:
                    await OrganizationUser.create(organization=organization, user=user, role=role)
                except IntegrityError:
                    pass  # joined in parallel
                logger.info('User {} joined organization {} through SSO', user.id, organization.id)
            if identity is None:
                identity = await SsoIdentity.create(
                    provider=provider, user=user, subject=claims.subject, created_user=created_user
                )
            await cls._remember_claims(identity, claims)
            pair = await SsoSessionService.start(user, identity, provider, tokens)
        return CallbackResult(
            redirect_to=request.redirect_path or DEFAULT_REDIRECT,
            intent=SsoLoginIntent.LOGIN,
            organization=organization,
            tokens=pair,
        )

    @staticmethod
    async def _existing_user(provider: SsoProvider, claims: SsoClaims) -> User | None:
        if not claims.email:
            return None
        user = await User.filter(email__iexact=claims.email).first()
        if user is None:
            return None
        if not claims.email_verified:
            raise OidcError(
                'email_not_verified',
                'Провайдер не подтвердил вашу почту, поэтому вход нельзя связать с аккаунтом автоматически. '
                'Войдите по паролю и привяжите провайдера в профиле',
            )
        if await SsoIdentity.exists(provider=provider, user=user):
            raise OidcError('identity_conflict', 'К этому аккаунту Hearfolio уже привязан другой аккаунт провайдера')
        return user

    @staticmethod
    def _check_rules(provider: SsoProvider, claims: SsoClaims) -> None:
        if not SsoRules.domain_allowed(provider, claims):
            domains = ', '.join(provider.allowed_email_domains or [])
            raise OidcError('domain_not_allowed', f'Вход разрешён только с подтверждённой почтой домена {domains}')
        if not SsoRules.groups_allowed(provider, claims):
            raise OidcError('group_required', 'У вас нет нужной группы у провайдера. Обратитесь к администратору')

    @staticmethod
    async def _create_user(claims: SsoClaims) -> User:
        if not claims.email:
            raise OidcError('email_required', 'Провайдер не сообщил почту: администратору нужно добавить scope email')
        if not claims.email_verified:
            raise OidcError('email_not_verified', 'Провайдер не подтвердил вашу почту, создать аккаунт нельзя')
        try:
            email = _email_adapter.validate_python(claims.email)
        except ValidationError as e:
            raise OidcError('email_invalid', 'Провайдер сообщил почту, которую Hearfolio не принимает') from e
        first_name, last_name = claims.given_name, claims.family_name
        if not first_name and not last_name:
            first_name, _, last_name = (claims.name or email.partition('@')[0]).partition(' ')
        user = User(email=email, first_name=first_name[:128], last_name=last_name.strip()[:128])
        # The account signs in through the provider; this password is never shown to anyone.
        await user.set_password_async(secrets.token_urlsafe(32))
        try:
            await user.save()
        except IntegrityError as e:
            raise OidcError('email_taken', 'Аккаунт с этой почтой уже существует. Войдите по паролю') from e
        return user

    @staticmethod
    async def _remember_claims(identity: SsoIdentity, claims: SsoClaims) -> None:
        identity.email = claims.email[:255]
        identity.email_verified = claims.email_verified
        identity.name = claims.name[:255]
        identity.groups = claims.groups
        identity.last_login_at = utcnow()
        await identity.save()

    # LINK (profile)

    @classmethod
    async def _link(
        cls,
        request: SsoLoginRequest,
        provider: SsoProvider,
        organization: Organization,
        claims: SsoClaims,
        tokens: dict[str, Any],
    ) -> CallbackResult:
        user = request.user
        if user is None or not user.is_active:
            raise OidcError('invalid_state', 'Войдите в Hearfolio и начните привязку заново')
        identity = await SsoIdentity.get_or_none(provider=provider, subject=claims.subject)
        if identity is not None and identity.user_id != user.id:
            raise OidcError('identity_taken', 'Этот аккаунт провайдера уже привязан к другому пользователю Hearfolio')
        if identity is None:
            if await SsoIdentity.exists(provider=provider, user=user):
                raise OidcError(
                    'identity_conflict', 'У вас уже привязан другой аккаунт этого провайдера. Сначала отвяжите его'
                )
            try:
                identity = await SsoIdentity.create(provider=provider, user=user, subject=claims.subject)
            except IntegrityError as e:
                raise OidcError('identity_conflict', 'Аккаунт провайдера уже привязан') from e
        await cls._remember_claims(identity, claims)
        pair = None
        # The linked account also signs this browser in through the provider, so an «SSO only» organization opens
        # right away — as long as the organization's rules let this account in.
        if SsoRules.allows_access(provider, claims):
            pair = await SsoSessionService.start(user, identity, provider, tokens)
        return CallbackResult(
            redirect_to=request.redirect_path or PROFILE_REDIRECT,
            intent=SsoLoginIntent.LINK,
            organization=organization,
            tokens=pair,
        )

    # PROFILE

    @staticmethod
    async def unlink(identity: SsoIdentity) -> None:
        if identity.created_user and await SsoIdentity.filter(user_id=identity.user_id).count() == 1:
            raise AppException.from_attrs(
                ErrorCode.CONFLICT,
                'Это единственный способ входа в ваш аккаунт. Попросите администратора сервера задать вам пароль',
                details={'reason': 'only_sign_in'},
            )
        await SsoSessionService.revoke_where('unlinked', identity_id=identity.id)
        await identity.delete()

    # CLEANUP

    @staticmethod
    async def purge_stale_requests() -> int:
        return await SsoLoginRequest.filter(expires_at__lt=utcnow() - LOGIN_REQUEST_RETENTION).delete()
