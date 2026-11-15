from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints

from app.core.models import BaseSchema
from app.domains.organization.models import OrganizationRole
from app.domains.sso.models import MAX_REVALIDATE_MINUTES, MIN_REVALIDATE_MINUTES, SsoJoinPolicy, SsoLoginMode

Scope = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r'^[\x21-\x7e]+$')]
Group = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Domain = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, max_length=253, pattern=r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)+$'
    ),
]
RedirectPath = Annotated[str, StringConstraints(max_length=1024)]

# PROVIDER_SCHEMAS (org admins, `Organization-Key`)


class SsoProviderReadSchema(BaseSchema):
    """The organization's provider and rules as org admins see them; the client secret is never returned."""

    issuer: str
    client_id: str
    has_client_secret: bool
    scopes: list[str]
    button_label: str
    login_mode: SsoLoginMode
    join_policy: SsoJoinPolicy
    allowed_email_domains: list[str]
    required_groups: list[str]
    default_role: OrganizationRole
    owner_password_fallback: bool
    revalidate_interval_minutes: int
    # From discovery: what the provider supports
    authorization_endpoint: str | None
    userinfo_endpoint: str | None
    scopes_supported: list[str] | None
    metadata_fetched_at: datetime | None
    updated_at: datetime


class SsoSettingsSchema(BaseSchema):
    """What the «Вход и участники» screen needs: the provider (null when not connected) and the URLs to register."""

    provider: SsoProviderReadSchema | None
    # Register exactly this redirect URI at the provider.
    redirect_uri: str
    # The organization's public sign-in page.
    login_url: str
    organization_key: str


class SsoProviderUpdateSchema(BaseSchema):
    """
    Connect or change the provider. Connecting needs `issuer`, `client_id` and `client_secret`; later every field is
    optional. A new issuer or client id needs the secret again. Discovery is fetched and validated on save.
    """

    issuer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)] | None = None
    client_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    client_secret: Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None = None
    scopes: Annotated[list[Scope], Field(max_length=20)] | None = None
    button_label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)] | None = None
    login_mode: SsoLoginMode | None = None
    join_policy: SsoJoinPolicy | None = None
    allowed_email_domains: Annotated[list[Domain], Field(max_length=50)] | None = None
    required_groups: Annotated[list[Group], Field(max_length=50)] | None = None
    default_role: OrganizationRole | None = None
    owner_password_fallback: bool | None = None
    revalidate_interval_minutes: Annotated[int, Field(ge=MIN_REVALIDATE_MINUTES, le=MAX_REVALIDATE_MINUTES)] | None = (
        None
    )

    model_config = ConfigDict(extra='forbid')


class SsoConnectionTestSchema(BaseSchema):
    """Unsaved values to check; omitted ones come from the saved provider."""

    issuer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)] | None = None
    client_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    client_secret: Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None = None
    scopes: Annotated[list[Scope], Field(max_length=20)] | None = None

    model_config = ConfigDict(extra='forbid')


class SsoCheckSchema(BaseSchema):
    label: str
    ok: bool
    message: str


class SsoConnectionTestResultSchema(BaseSchema):
    ok: bool
    checks: list[SsoCheckSchema]
    # Requested scopes the provider does not list in `scopes_supported` (not an error: lists are often partial).
    unsupported_scopes: list[str]


# PUBLIC SIGN-IN


class SsoOrganizationSchema(BaseSchema):
    """Public: an organization that signs in through a provider (`/sso/{key}` page)."""

    organization_name: str
    organization_key: str
    button_label: str
    login_mode: SsoLoginMode
    join_policy: SsoJoinPolicy


class SsoStartSchema(BaseSchema):
    """Start a sign-in: by organization key, or by email (its domain picks the organization)."""

    organization_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = (
        None
    )
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)] | None = None
    # Same-site path to return to (`/oauth/authorize?...` for the app sign-in), else `/home`.
    redirect: RedirectPath | None = None

    model_config = ConfigDict(extra='forbid')


class SsoLinkSchema(BaseSchema):
    organization_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    redirect: RedirectPath | None = None

    model_config = ConfigDict(extra='forbid')


class SsoAuthorizationSchema(BaseSchema):
    """Where to send the browser: the provider's authorization endpoint with state, nonce and PKCE."""

    authorization_url: str


# LINKED ACCOUNTS (profile)


class SsoIdentityReadSchema(BaseSchema):
    id: UUID
    organization_id: UUID
    organization_name: str
    organization_key: str
    provider_label: str
    issuer: str
    email: str
    name: str
    # Unlinking would leave the account without a way to sign in (created by SSO, no other link).
    is_only_sign_in: bool
    created_at: datetime
    last_login_at: datetime | None
