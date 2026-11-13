from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, Field

from app.core.settings import settings

# Special-use names that self-hosted teams use for internal mail (RFC 6762 `.local`, RFC 8375 `home.arpa`, `.test`).
# email-validator always rejects them; `ALLOW_LOCAL_EMAIL_DOMAINS=true` lets them through. `.lan` and `.internal`
# are not special-use and always pass.
LOCAL_EMAIL_SUFFIXES = ('local', 'home.arpa', 'test')
# A neutral stand-in for the suffix, so every other rule (syntax, a period in the domain) still applies.
_PROBE_SUFFIX = 'example'


def normalize_email(value: str) -> str:
    return value.strip().lower()


def _local_suffix(domain: str) -> str | None:
    return next((s for s in LOCAL_EMAIL_SUFFIXES if domain == s or domain.endswith(f'.{s}')), None)


def validate_normalized_email(value: str) -> str:
    value = normalize_email(value)
    probe = value
    suffix = _local_suffix(value.rpartition('@')[2]) if settings.allow_local_email_domains else None
    if suffix:
        probe = f'{value[: -len(suffix)]}{_PROBE_SUFFIX}'
    try:
        validate_email(probe, check_deliverability=False)
    except EmailNotValidError as error:
        raise ValueError(f'value is not a valid email address: {error}') from error
    return value


# Validated address, stored lowercase. Use for fields that create or change an email.
NormalizedEmail = Annotated[
    str,
    Field(max_length=320, json_schema_extra={'format': 'email'}),
    AfterValidator(validate_normalized_email),
]

# Lowercased but not validated: login must still find accounts stored before validation existed.
LoginEmail = Annotated[str, Field(max_length=320), AfterValidator(normalize_email)]
