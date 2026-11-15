from typing import Annotated
from urllib.parse import quote, urlencode
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from fastapi_ronin.decorators import action, viewset
from fastapi_ronin.permissions import BasePermission, IsAuthenticated
from loguru import logger

from app.core.auth import get_current_auth_state
from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.services.crypto_service import CryptoService
from app.core.services.rate_limiter import invite_rate_limiter
from app.core.settings import settings
from app.core.utils.request_utils import client_ip, public_base_url
from app.core.viewsets import BaseGenericViewSet
from app.domains.auth.transport import set_auth_cookies
from app.domains.organization.models import Organization
from app.domains.sso.models import SsoIdentity, SsoLoginIntent, SsoLoginRequest, SsoProvider
from app.domains.sso.schemas import (
    SsoAuthorizationSchema,
    SsoConnectionTestResultSchema,
    SsoConnectionTestSchema,
    SsoIdentityReadSchema,
    SsoLinkSchema,
    SsoOrganizationSchema,
    SsoProviderUpdateSchema,
    SsoSettingsSchema,
    SsoStartSchema,
)
from app.domains.sso.services.login_service import CallbackParams, SsoLoginService
from app.domains.sso.services.oidc_client import OidcError
from app.domains.sso.services.provider_service import SsoProviderService
from app.shared.permissions.is_organization_admin import IsOrganizationAdmin

sso_provider_router = APIRouter(prefix='/sso-provider', tags=['sso-provider'])
sso_router = APIRouter(prefix='/sso', tags=['sso'])
routers = (sso_provider_router, sso_router)

BROWSER_COOKIE = 'sso_browser'
BROWSER_COOKIE_PATH = '/api/v1/sso'


def _current_organization() -> Organization:
    organization = get_current_auth_state().organization
    if organization is None:
        raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Organization-Key header is required')
    return organization


def _set_browser_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        key=BROWSER_COOKIE,
        value=value,
        max_age=settings.sso_login_request_ttl_seconds,
        path=BROWSER_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite='lax',
    )


@viewset(sso_provider_router)
class SsoProviderViewSet(BaseGenericViewSet[SsoProvider]):
    """The `Organization-Key` organization's OpenID Connect provider and sign-in rules. Org admins only."""

    model = SsoProvider

    async def get_permissions(self) -> list[BasePermission]:
        return [IsAuthenticated(), IsOrganizationAdmin()]

    @action(methods=['GET'])
    async def current(self, request: Request) -> SsoSettingsSchema:
        """The provider (null when none is connected), the redirect URI to register and the public sign-in URL."""
        return await SsoProviderService.settings(_current_organization(), public_base_url(request))

    @action(methods=['PATCH'], path='current')
    async def update_current(self, request: Request, data: SsoProviderUpdateSchema) -> SsoSettingsSchema:
        """Connect or change the provider and rules; discovery is fetched and validated. The secret is never returned."""
        organization = _current_organization()
        await SsoProviderService.update(organization, data, self.user, get_current_auth_state().sso_provider_id)
        return await SsoProviderService.settings(organization, public_base_url(request))

    @action(methods=['DELETE'], path='current', status_code=204)
    async def destroy_current(self) -> None:
        """Disconnect the provider: its sessions end, links are deleted, members sign in with passwords again."""
        provider = await SsoProviderService.get(_current_organization())
        if provider is None:
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, 'Провайдер не подключён')
        await SsoProviderService.delete(provider)

    @action(methods=['POST'], path='test')
    async def test_connection(self, request: Request, data: SsoConnectionTestSchema) -> SsoConnectionTestResultSchema:
        """Check discovery, signing keys and the client credentials (saved, or the unsaved values in the body)."""
        organization = _current_organization()
        provider = await SsoProviderService.get(organization)
        return await SsoProviderService.test(organization, provider, data, public_base_url(request))


@viewset(sso_router)
class SsoViewSet(BaseGenericViewSet[SsoIdentity]):
    """
    Sign-in through an organization's provider (public: `organization`, `start`; the browser callback is a plain
    route below) and the caller's linked provider accounts.
    """

    model = SsoIdentity
    organization_header = False

    def get_permissions(self):
        if self.action in ('organization', 'start'):
            return []
        return [IsAuthenticated()]

    @action(methods=['GET'], path='organizations/{key}')
    async def organization(self, request: Request, key: str) -> SsoOrganizationSchema:
        """Public: whether an organization signs in through a provider, and how the button is labelled."""
        if retry_after := await invite_rate_limiter.retry_after(client_ip(request)):
            raise AppException.from_attrs(
                ErrorCode.RATE_LIMITED, 'Too many attempts', headers={'Retry-After': str(retry_after)}
            )
        try:
            provider = await SsoLoginService.provider_by_key(key)
        except AppException:
            await invite_rate_limiter.hit(client_ip(request))
            raise
        return SsoOrganizationSchema(
            organization_name=provider.organization.name,
            organization_key=provider.organization.key,
            button_label=provider.button_label,
            login_mode=provider.login_mode,
            join_policy=provider.join_policy,
        )

    @action(methods=['POST'])
    async def start(self, request: Request, response: Response, data: SsoStartSchema) -> SsoAuthorizationSchema:
        """
        Public: begin a sign-in by organization key or work email (its domain finds the organization). Returns the
        provider URL to open; sets the HttpOnly `sso_browser` cookie that ties the callback to this browser.
        """
        if data.organization_key:
            provider = await SsoLoginService.provider_by_key(data.organization_key)
        elif data.email:
            provider = await SsoLoginService.provider_by_email(data.email)
        else:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Укажите ключ организации или рабочую почту')
        url, browser = await SsoLoginService.start(
            provider,
            base_url=public_base_url(request),
            browser_token=request.cookies.get(BROWSER_COOKIE),
            redirect=data.redirect,
            login_hint=data.email,
        )
        _set_browser_cookie(response, browser)
        return SsoAuthorizationSchema(authorization_url=url)

    @action(methods=['POST'])
    async def link(self, request: Request, response: Response, data: SsoLinkSchema) -> SsoAuthorizationSchema:
        """Link the caller's account to an organization's provider (profile «Связанные аккаунты»)."""
        provider = await SsoLoginService.provider_by_key(data.organization_key)
        url, browser = await SsoLoginService.start(
            provider,
            base_url=public_base_url(request),
            browser_token=request.cookies.get(BROWSER_COOKIE),
            intent=SsoLoginIntent.LINK,
            user=self.user,
            redirect=data.redirect,
        )
        _set_browser_cookie(response, browser)
        return SsoAuthorizationSchema(authorization_url=url)

    @action(methods=['GET'])
    async def identities(self) -> list[SsoIdentityReadSchema]:
        """Provider accounts linked to the caller."""
        identities = await SsoIdentity.filter(user_id=self.user.id).select_related('provider__organization')
        created_only = len(identities) == 1
        return [
            SsoIdentityReadSchema(
                id=identity.id,
                organization_id=identity.provider.organization_id,
                organization_name=identity.provider.organization.name,
                organization_key=identity.provider.organization.key,
                provider_label=identity.provider.button_label,
                issuer=identity.provider.issuer,
                email=identity.email,
                name=identity.name,
                is_only_sign_in=identity.created_user and created_only,
                created_at=identity.created_at,
                last_login_at=identity.last_login_at,
            )
            for identity in identities
        ]

    @action(methods=['DELETE'], path='identities/{identity}', status_code=204)
    async def unlink(self, identity: UUID) -> None:
        """Unlink a provider account; the sessions established through it end."""
        linked = await SsoIdentity.get_or_none(id=identity, user_id=self.user.id)
        if linked is None:
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, 'Связанный аккаунт не найден')
        await SsoLoginService.unlink(linked)


def _error_redirect(intent: SsoLoginIntent | None, reason: str, organization_key: str | None) -> str:
    """Back to the page the sign-in started from, with the reason (the web app words it in Russian)."""
    query = urlencode({'sso_error': reason})
    if intent == SsoLoginIntent.LINK:
        return f'/settings/profile?{query}'
    if organization_key:
        return f'/sso/{quote(organization_key, safe="")}?{query}'
    return f'/auth?{query}'


# Browser-only: the provider redirects here. Not part of the client API, so it stays out of the OpenAPI schema.
@sso_router.get('/callback/{organization_id}', include_in_schema=False)
async def sso_callback(
    request: Request,
    organization_id: UUID,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
    iss: Annotated[str | None, Query(max_length=512)] = None,
) -> RedirectResponse:
    base_url = public_base_url(request)
    try:
        result = await SsoLoginService.callback(
            organization_id,
            CallbackParams(code=code, state=state, error=error, iss=iss),
            base_url=base_url,
            browser_token=request.cookies.get(BROWSER_COOKIE),
        )
    except OidcError as failure:
        logger.info('SSO sign-in for organization {} failed: {} ({})', organization_id, failure.reason, failure.message)
        organization = await Organization.get_or_none(id=organization_id)
        target = _error_redirect(None, failure.reason, organization.key if organization else None)
        if failure.reason not in ('invalid_state', 'browser_mismatch') and state:
            pending = await SsoLoginRequest.get_or_none(state_hash=CryptoService.hash_value(state))
            if pending is not None and pending.intent == SsoLoginIntent.LINK:
                target = _error_redirect(SsoLoginIntent.LINK, failure.reason, None)
        return RedirectResponse(base_url + target, status_code=303)
    response = RedirectResponse(base_url + result.redirect_to, status_code=303)
    if result.tokens is not None:
        set_auth_cookies(response, result.tokens)
    return response
