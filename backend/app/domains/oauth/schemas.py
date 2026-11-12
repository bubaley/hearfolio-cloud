from typing import Literal

from pydantic import Field

from app.core.models import BaseSchema
from app.domains.auth.schemas import MeSchema


class OAuthAuthorizeRequest(BaseSchema):
    """What the native app put into `/oauth/authorize?...`, forwarded by the consent page."""

    client_id: str = Field(max_length=64)
    redirect_uri: str = Field(max_length=255)
    code_challenge: str = Field(max_length=128)
    code_challenge_method: str = Field('S256', max_length=16)
    state: str | None = Field(None, max_length=512)
    device_name: str = Field(min_length=1, max_length=64)
    # Standard parameters some OAuth libraries always send: `response_type` must be `code` when present, `scope`
    # is accepted and ignored (an app token has the user's full access).
    response_type: str | None = Field(None, max_length=32)
    scope: str | None = Field(None, max_length=512)


class OAuthAuthorizeInfoSchema(BaseSchema):
    """A validated authorization request, for the consent screen."""

    client_id: str
    client_name: str
    redirect_uri: str
    device_name: str


class OAuthAuthorizeResponse(BaseSchema):
    """The single-use code (valid 60 s) and where to send the browser: `redirect_uri?code=...&state=...`."""

    code: str
    state: str | None
    redirect_to: str


class OAuthTokenRequest(BaseSchema):
    """RFC 6749 §4.1.3 + RFC 7636. Sent as form (`application/x-www-form-urlencoded`) or JSON."""

    grant_type: str | None = None
    code: str | None = None
    code_verifier: str | None = None
    redirect_uri: str | None = None
    client_id: str | None = None


class OAuthTokenResponse(MeSchema):
    """A regular named API token (`Authorization: Token <access_token>`), plus the user and their organizations."""

    access_token: str
    token_type: Literal['Token'] = 'Token'


class OAuthErrorResponse(BaseSchema):
    """RFC 6749 §5.2 error body of the token and revoke endpoints."""

    error: str
    error_description: str | None = None
