from enum import StrEnum
from uuid import UUID

from tortoise import fields

from app.core.models import BaseModel
from app.core.scope import Scope, Unscoped
from app.domains.organization.models import OrganizationRole

# offline_access: most providers issue a refresh token only for it; groups: for the group rule.
DEFAULT_SCOPES = ['openid', 'email', 'profile', 'groups', 'offline_access']
DEFAULT_REVALIDATE_MINUTES = 10
MIN_REVALIDATE_MINUTES = 5
MAX_REVALIDATE_MINUTES = 60


class SsoLoginMode(StrEnum):
    # Password and SSO both open the organization.
    PASSWORD_AND_SSO = 'password_and_sso'
    # Only a session established through this provider opens the organization (owner break-glass aside).
    SSO_ONLY = 'sso_only'


class SsoJoinPolicy(StrEnum):
    # Only existing members (added or invited) can sign in through the provider.
    INVITE_ONLY = 'invite_only'
    # Anyone the provider authenticates joins with `default_role`, if the domain/group rules pass.
    PROVIDER = 'provider'


class SsoProvider(BaseModel):
    """
    The OpenID Connect provider an organization signs in with, plus the organization's sign-in rules. Hearfolio is
    the relying party and knows nothing provider-specific: everything comes from discovery and these fields.
    """

    organization = fields.OneToOneField('models.Organization', related_name='sso_provider', on_delete=fields.CASCADE)
    organization_id: UUID

    # Connection
    issuer = fields.CharField(max_length=512)
    client_id = fields.CharField(max_length=255)
    # Fernet ciphertext from CryptoService; never serialized.
    client_secret_encrypted = fields.TextField()
    scopes = fields.JSONField(default=list)
    button_label = fields.CharField(max_length=64, default='')
    # Discovery document fields Hearfolio uses (endpoints, algorithms, auth methods), refreshed on save/test.
    metadata = fields.JSONField(default=dict)
    metadata_fetched_at = fields.DatetimeField(null=True)

    # Rules
    login_mode = fields.CharEnumField(SsoLoginMode, max_length=24, default=SsoLoginMode.PASSWORD_AND_SSO)
    join_policy = fields.CharEnumField(SsoJoinPolicy, max_length=24, default=SsoJoinPolicy.INVITE_ONLY)
    # Lowercase domains; empty: any. The provider must report the email as verified for a domain to count.
    allowed_email_domains = fields.JSONField(default=list)
    # Values of the `groups` claim; the user needs at least one. Empty: no group rule.
    required_groups = fields.JSONField(default=list)
    default_role = fields.CharEnumField(OrganizationRole, max_length=16, default=OrganizationRole.MEMBER)
    # SSO only: owners keep password access, so a broken provider cannot lock the organization out.
    owner_password_fallback = fields.BooleanField(default=True)
    # How often a session established through the provider is re-checked against it (refresh token / userinfo).
    revalidate_interval_minutes = fields.IntField(default=DEFAULT_REVALIDATE_MINUTES)

    tenant_scope = Scope(user='organization__org_users__user_id', organization='organization_id')

    class Meta:
        table = 'sso_provider'


class SsoIdentity(BaseModel):
    """A provider account (`sub`, stable per provider) linked to a Hearfolio user. Never matched by email alone."""

    provider = fields.ForeignKeyField('models.SsoProvider', related_name='identities', on_delete=fields.CASCADE)
    provider_id: UUID
    user = fields.ForeignKeyField('models.User', related_name='sso_identities', on_delete=fields.CASCADE)
    user_id: UUID
    subject = fields.CharField(max_length=255)
    # Last values the provider reported; informational, never used to find the user.
    email = fields.CharField(max_length=255, default='')
    email_verified = fields.BooleanField(default=False)
    name = fields.CharField(max_length=255, default='')
    groups = fields.JSONField(default=list)
    # The account was created by this sign-in (no password the user knows).
    created_user = fields.BooleanField(default=False)
    last_login_at = fields.DatetimeField(null=True)

    tenant_scope = Scope(user='user_id')

    class Meta:
        table = 'sso_identity'
        unique_together = (('provider', 'subject'), ('provider', 'user'))
        ordering = ('created_at',)


class SsoSession(BaseModel):
    """
    A Hearfolio session established through a provider: the web session family (`family_id` of RefreshSession)
    and the app tokens approved from it (`SsoSessionToken`). Holds the provider tokens for revalidation.
    """

    provider = fields.ForeignKeyField('models.SsoProvider', related_name='sessions', on_delete=fields.CASCADE)
    provider_id: UUID
    identity = fields.ForeignKeyField('models.SsoIdentity', related_name='sessions', on_delete=fields.CASCADE)
    identity_id: UUID
    user = fields.ForeignKeyField('models.User', related_name='sso_sessions', on_delete=fields.CASCADE)
    user_id: UUID
    family_id = fields.UUIDField(unique=True)
    # Fernet ciphertexts; empty when the provider gave none.
    refresh_token_encrypted = fields.TextField(default='')
    access_token_encrypted = fields.TextField(default='')
    # When the provider access token expires (from `expires_in`); unknown: null.
    access_token_expires_at = fields.DatetimeField(null=True)
    # Last successful check against the provider (sign-in counts).
    validated_at = fields.DatetimeField()
    # A check in flight since then (at most one per session across processes).
    check_started_at = fields.DatetimeField(null=True)
    revoked_at = fields.DatetimeField(null=True)
    revoke_reason = fields.CharField(max_length=32, default='')

    tenant_scope = Scope(user='user_id')

    class Meta:
        table = 'sso_session'
        ordering = ('created_at',)


class SsoSessionToken(BaseModel):
    """An app API token approved (OAuth consent) from an SSO session: it lives and dies with that session."""

    session = fields.ForeignKeyField('models.SsoSession', related_name='tokens', on_delete=fields.CASCADE)
    session_id: UUID
    token = fields.OneToOneField('models.UserToken', related_name='sso_session_link', on_delete=fields.CASCADE)
    token_id: UUID

    tenant_scope = Scope(user='session__user_id')

    class Meta:
        table = 'sso_session_token'


class SsoLoginIntent(StrEnum):
    LOGIN = 'login'
    LINK = 'link'


class SsoLoginRequest(BaseModel):
    """
    A pending authorization request: `state` (stored as SHA-256), `nonce`, the PKCE verifier and the browser it
    belongs to (hash of an HttpOnly cookie). Single use, short-lived.
    """

    provider = fields.ForeignKeyField('models.SsoProvider', related_name='login_requests', on_delete=fields.CASCADE)
    provider_id: UUID
    state_hash = fields.CharField(max_length=64, unique=True)
    browser_hash = fields.CharField(max_length=64)
    nonce = fields.CharField(max_length=128)
    code_verifier_encrypted = fields.TextField()
    intent = fields.CharEnumField(SsoLoginIntent, max_length=8, default=SsoLoginIntent.LOGIN)
    # The signed-in user who links an account (intent=link).
    user = fields.ForeignKeyField('models.User', related_name='sso_login_requests', null=True, on_delete=fields.CASCADE)
    user_id: UUID | None
    redirect_path = fields.CharField(max_length=1024, default='')
    expires_at = fields.DatetimeField()
    used_at = fields.DatetimeField(null=True)

    tenant_scope = Unscoped(reason='Looked up by the state hash in the provider callback, before anyone is signed in')

    class Meta:
        table = 'sso_login_request'
        ordering = ('created_at',)
