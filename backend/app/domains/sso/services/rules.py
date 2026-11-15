from dataclasses import dataclass
from typing import Any

from app.domains.sso.models import SsoIdentity, SsoJoinPolicy, SsoProvider
from app.domains.sso.services.oidc_client import normalize_groups


@dataclass(frozen=True)
class SsoClaims:
    """The user attributes Hearfolio reads from the ID token and userinfo (standard claims + `groups`)."""

    subject: str
    email: str
    email_verified: bool
    name: str
    given_name: str
    family_name: str
    groups: list[str]

    @property
    def email_domain(self) -> str:
        return self.email.rpartition('@')[2] if '@' in self.email else ''

    @classmethod
    def from_claims(cls, claims: dict[str, Any], fallback: SsoIdentity | None = None) -> SsoClaims:
        """Claims the provider omitted this time keep the values stored on `fallback`."""

        def text(name: str, default: str = '') -> str:
            value = claims.get(name)
            return value.strip() if isinstance(value, str) else default

        email = text('email', fallback.email if fallback else '').lower()
        verified = claims.get('email_verified')
        if isinstance(verified, str):  # some providers send "true"
            verified = verified.lower() == 'true'
        if not isinstance(verified, bool):
            verified = bool(fallback and fallback.email_verified and fallback.email == email)
        groups = normalize_groups(claims['groups']) if 'groups' in claims else list(fallback.groups if fallback else [])
        return cls(
            subject=text('sub', fallback.subject if fallback else ''),
            email=email,
            email_verified=verified,
            name=text('name', fallback.name if fallback else ''),
            given_name=text('given_name'),
            family_name=text('family_name'),
            groups=groups,
        )


class SsoRules:
    """The organization's rules on who may use its provider."""

    @staticmethod
    def domain_allowed(provider: SsoProvider, claims: SsoClaims) -> bool:
        domains = provider.allowed_email_domains or []
        if not domains:
            return True
        return claims.email_verified and claims.email_domain in domains

    @staticmethod
    def groups_allowed(provider: SsoProvider, claims: SsoClaims) -> bool:
        required = provider.required_groups or []
        return not required or any(group in claims.groups for group in required)

    @classmethod
    def allows_access(cls, provider: SsoProvider, claims: SsoClaims) -> bool:
        """Domain and group rules: checked on every sign-in and revalidation."""
        return cls.domain_allowed(provider, claims) and cls.groups_allowed(provider, claims)

    @classmethod
    def allows_join(cls, provider: SsoProvider, claims: SsoClaims) -> bool:
        return provider.join_policy == SsoJoinPolicy.PROVIDER and cls.allows_access(provider, claims)
