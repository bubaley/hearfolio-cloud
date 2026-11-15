import secrets
from typing import Any
from uuid import UUID

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.services.crypto_service import CryptoService
from app.core.utils.date_utils import utcnow
from app.domains.organization.models import Organization, OrganizationRole
from app.domains.organization.services.organization_service import OrganizationService
from app.domains.sso.models import DEFAULT_SCOPES, SsoIdentity, SsoLoginMode, SsoProvider
from app.domains.sso.schemas import (
    SsoCheckSchema,
    SsoConnectionTestResultSchema,
    SsoConnectionTestSchema,
    SsoProviderReadSchema,
    SsoProviderUpdateSchema,
    SsoSettingsSchema,
)
from app.domains.sso.services.login_service import SsoLoginService
from app.domains.sso.services.oidc_client import OidcClient, OidcError
from app.domains.sso.services.session_service import SsoSessionService
from app.domains.user.models import User

CONNECTION_FIELDS_REQUIRED = 'Чтобы подключить провайдера, укажите его адрес (issuer), client id и client secret'
SECRET_REQUIRED = 'При смене адреса провайдера или client id укажите client secret заново'
OWNER_DEFAULT_ROLE = 'Новые участники не могут получать роль владельца'
LOCKOUT = (
    'Чтобы включить «Только SSO», сначала войдите через этого провайдера '
    '(или оставьте владельцам вход по паролю на случай сбоя провайдера)'
)


def _validation_error(message: str, reason: str) -> AppException:
    return AppException.from_attrs(ErrorCode.VALIDATION_ERROR, message, details={'reason': reason})


def oidc_to_app_exception(error: OidcError) -> AppException:
    return AppException.from_attrs(ErrorCode.VALIDATION_ERROR, error.message, details={'reason': error.reason})


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    values = list(dict.fromkeys(scopes if scopes is not None else DEFAULT_SCOPES))
    return ['openid', *[scope for scope in values if scope != 'openid']]


class SsoProviderService:
    """The organization's provider connection and rules (org admins, «Вход и участники»)."""

    @staticmethod
    async def get(organization: Organization) -> SsoProvider | None:
        return await SsoProvider.get_or_none(organization_id=organization.id)

    @staticmethod
    def to_read(provider: SsoProvider) -> SsoProviderReadSchema:
        metadata: dict[str, Any] = provider.metadata or {}
        scopes_supported = metadata.get('scopes_supported')
        return SsoProviderReadSchema(
            issuer=provider.issuer,
            client_id=provider.client_id,
            has_client_secret=bool(provider.client_secret_encrypted),
            scopes=list(provider.scopes or []),
            button_label=provider.button_label,
            login_mode=provider.login_mode,
            join_policy=provider.join_policy,
            allowed_email_domains=list(provider.allowed_email_domains or []),
            required_groups=list(provider.required_groups or []),
            default_role=provider.default_role,
            owner_password_fallback=provider.owner_password_fallback,
            revalidate_interval_minutes=provider.revalidate_interval_minutes,
            authorization_endpoint=metadata.get('authorization_endpoint'),
            userinfo_endpoint=metadata.get('userinfo_endpoint'),
            scopes_supported=list(scopes_supported) if isinstance(scopes_supported, list) else None,
            metadata_fetched_at=provider.metadata_fetched_at,
            updated_at=provider.updated_at,
        )

    @classmethod
    async def settings(cls, organization: Organization, base_url: str) -> SsoSettingsSchema:
        provider = await cls.get(organization)
        return SsoSettingsSchema(
            provider=cls.to_read(provider) if provider else None,
            redirect_uri=SsoLoginService.redirect_uri(base_url, organization.id),
            login_url=SsoLoginService.login_url(base_url, organization.key),
            organization_key=organization.key,
        )

    @staticmethod
    async def discover(issuer: str) -> dict[str, Any]:
        """Discovery plus the signing keys, so a saved provider is known to be usable."""
        try:
            metadata = await OidcClient.discover(issuer)
            jwks = await OidcClient.jwks(metadata['jwks_uri'], refresh=True)
        except OidcError as error:
            raise oidc_to_app_exception(error) from error
        if not jwks.get('keys'):
            raise _validation_error('Провайдер не опубликовал ключи подписи (JWKS пуст)', 'jwks_empty')
        return metadata

    # SAVE

    @classmethod
    async def update(
        cls,
        organization: Organization,
        data: SsoProviderUpdateSchema,
        actor: User,
        session_provider_id: UUID | None,
    ) -> SsoProvider:
        provider = await cls.get(organization)
        values = {name: getattr(data, name) for name in data.model_fields_set if getattr(data, name) is not None}
        creating = provider is None
        if provider is None:
            if not all(values.get(name) for name in ('issuer', 'client_id', 'client_secret')):
                raise _validation_error(CONNECTION_FIELDS_REQUIRED, 'connection_required')
            provider = SsoProvider(organization=organization, scopes=normalize_scopes(None))
        issuer_changed = 'issuer' in values and values['issuer'] != provider.issuer
        client_changed = 'client_id' in values and values['client_id'] != provider.client_id
        if not creating and (issuer_changed or client_changed) and 'client_secret' not in values:
            raise _validation_error(SECRET_REQUIRED, 'client_secret_required')
        if values.get('default_role') == OrganizationRole.OWNER:
            raise _validation_error(OWNER_DEFAULT_ROLE, 'owner_default_role')

        if issuer_changed or not provider.metadata:
            provider.metadata = await cls.discover(values.get('issuer', provider.issuer))
            # Store the issuer exactly as the provider names itself: ID tokens are checked against it.
            provider.issuer = provider.metadata['issuer']
            provider.metadata_fetched_at = utcnow()
        if 'client_id' in values:
            provider.client_id = values['client_id']
        if 'client_secret' in values:
            provider.client_secret_encrypted = CryptoService.encrypt(values['client_secret'])
        if 'scopes' in values:
            provider.scopes = normalize_scopes(values['scopes'])
        for name in (
            'button_label',
            'login_mode',
            'join_policy',
            'allowed_email_domains',
            'required_groups',
            'default_role',
            'owner_password_fallback',
            'revalidate_interval_minutes',
        ):
            if name in values:
                value = values[name]
                setattr(provider, name, list(dict.fromkeys(value)) if isinstance(value, list) else value)

        sessions_survive = not creating and not issuer_changed
        # Only what decides who reaches the organization is guarded; other rules stay editable in a working setup.
        if issuer_changed or values.keys() & {'login_mode', 'owner_password_fallback'}:
            await cls._check_lockout(provider, organization, actor, session_provider_id if sessions_survive else None)
        if not creating and issuer_changed:
            # Subjects are only unique per issuer: links and sessions of the old provider mean nothing now.
            await SsoSessionService.revoke_where('provider_changed', provider_id=provider.id)
            await SsoIdentity.filter(provider_id=provider.id).delete()
        await provider.save()
        SsoSessionService.forget_organization(organization.id)
        return provider

    @staticmethod
    async def _check_lockout(
        provider: SsoProvider, organization: Organization, actor: User, session_provider_id: UUID | None
    ) -> None:
        """«SSO only» must stay reachable: prove the provider works with this session, or keep owners' passwords."""
        if provider.login_mode != SsoLoginMode.SSO_ONLY or actor.is_superuser:
            return
        if session_provider_id is not None and session_provider_id == provider.id:
            return
        if provider.owner_password_fallback and await OrganizationService.is_owner(actor, organization.id):
            return
        raise _validation_error(LOCKOUT, 'sso_session_required')

    # DISCONNECT

    @staticmethod
    async def delete(provider: SsoProvider) -> None:
        """Every session established through it ends; members fall back to their passwords (or invites)."""
        await SsoSessionService.revoke_where('provider_removed', provider_id=provider.id)
        organization_id = provider.organization_id
        await provider.delete()
        SsoSessionService.forget_organization(organization_id)

    # TEST

    @classmethod
    async def test(
        cls, organization: Organization, provider: SsoProvider | None, data: SsoConnectionTestSchema, base_url: str
    ) -> SsoConnectionTestResultSchema:
        issuer = data.issuer or (provider.issuer if provider else None)
        if not issuer:
            raise _validation_error('Укажите адрес провайдера (issuer)', 'issuer_required')
        client_id = data.client_id or (provider.client_id if provider else '')
        secret = data.client_secret
        if secret is None and provider is not None and client_id == provider.client_id and issuer == provider.issuer:
            secret = CryptoService.decrypt(provider.client_secret_encrypted)
        checks: list[SsoCheckSchema] = []
        try:
            metadata = await OidcClient.discover(issuer)
        except OidcError as error:
            checks.append(SsoCheckSchema(label='Discovery', ok=False, message=error.message))
            return SsoConnectionTestResultSchema(ok=False, checks=checks, unsupported_scopes=[])
        checks.append(SsoCheckSchema(label='Discovery', ok=True, message=f'Провайдер {metadata["issuer"]} найден'))

        try:
            jwks = await OidcClient.jwks(metadata['jwks_uri'], refresh=True)
            count = len(jwks.get('keys') or [])
            checks.append(
                SsoCheckSchema(
                    label='Ключи подписи',
                    ok=count > 0,
                    message=f'Опубликовано ключей: {count}' if count else 'JWKS пуст: ID-токены нечем проверить',
                )
            )
        except OidcError as error:
            checks.append(SsoCheckSchema(label='Ключи подписи', ok=False, message=error.message))

        if client_id and secret:
            checks.append(await cls._probe_client(metadata, client_id, secret, organization, base_url))
        else:
            checks.append(
                SsoCheckSchema(
                    label='Client id и секрет', ok=False, message='Укажите client id и секрет, чтобы проверить их'
                )
            )

        checks.append(
            SsoCheckSchema(
                label='Userinfo',
                ok=True,
                message='Есть: данные пользователя перепроверяются при каждой проверке сеанса'
                if metadata.get('userinfo_endpoint')
                else 'Нет userinfo endpoint: данные берутся только из ID-токена',
            )
        )
        scopes = normalize_scopes(data.scopes if data.scopes is not None else (provider.scopes if provider else None))
        supported = metadata.get('scopes_supported')
        unsupported = [scope for scope in scopes if isinstance(supported, list) and scope not in supported]
        return SsoConnectionTestResultSchema(
            ok=all(check.ok for check in checks), checks=checks, unsupported_scopes=unsupported
        )

    @staticmethod
    async def _probe_client(
        metadata: dict[str, Any], client_id: str, secret: str, organization: Organization, base_url: str
    ) -> SsoCheckSchema:
        """
        Send a made-up code: a provider that accepts the client answers `invalid_grant` (the code is wrong),
        one that does not answers `invalid_client`. Nothing is signed in.
        """
        label = 'Client id и секрет'
        try:
            await OidcClient.token_request(
                metadata,
                client_id,
                secret,
                {
                    'grant_type': 'authorization_code',
                    'code': secrets.token_urlsafe(24),
                    'redirect_uri': SsoLoginService.redirect_uri(base_url, organization.id),
                    'code_verifier': secrets.token_urlsafe(48),
                },
            )
        except OidcError as error:
            if error.oauth_error == 'invalid_client':
                return SsoCheckSchema(label=label, ok=False, message='Провайдер не принял client id или секрет')
            if error.transient:
                return SsoCheckSchema(label=label, ok=False, message=error.message)
            if error.oauth_error == 'invalid_grant':
                return SsoCheckSchema(label=label, ok=True, message='Провайдер принял client id и секрет')
            return SsoCheckSchema(
                label=label,
                ok=True,
                message=f'Провайдер ответил «{error.oauth_error or "ошибка"}»: секрет окончательно проверится при первом входе',
            )
        return SsoCheckSchema(label=label, ok=True, message='Провайдер принял client id и секрет')
