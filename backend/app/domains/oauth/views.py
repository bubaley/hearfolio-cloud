from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi_ronin.decorators import action, viewset
from fastapi_ronin.permissions import IsAuthenticated
from pydantic import ValidationError

from app.core.auth import get_current_auth_state
from app.core.utils.request_utils import client_ip
from app.core.viewsets import BaseGenericViewSet
from app.domains.auth.schemas import MeSchema
from app.domains.oauth.models import OAuthAuthorizationCode
from app.domains.oauth.schemas import (
    OAuthAuthorizeInfoSchema,
    OAuthAuthorizeRequest,
    OAuthAuthorizeResponse,
    OAuthErrorResponse,
    OAuthTokenRequest,
    OAuthTokenResponse,
)
from app.domains.oauth.services.oauth_service import OAuthError, OAuthErrorCode, OAuthService

oauth_router = APIRouter(prefix='/oauth', tags=['oauth'])
routers = (oauth_router,)

NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}
FORM = 'application/x-www-form-urlencoded'
TOKEN_REQUEST_BODY: dict[str, Any] = {
    'requestBody': {
        'required': True,
        'content': {
            FORM: {'schema': OAuthTokenRequest.model_json_schema()},
            'application/json': {'schema': OAuthTokenRequest.model_json_schema()},
        },
    }
}


async def oauth_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Registered in `main.py` for `OAuthError`: the RFC 6749 §5.2 body instead of the API error envelope."""
    error = exc if isinstance(exc, OAuthError) else OAuthError(OAuthErrorCode.INVALID_REQUEST, str(exc))
    body = OAuthErrorResponse(error=error.error, error_description=error.description)
    return JSONResponse(
        status_code=error.status_code, content=body.model_dump(), headers={**NO_STORE, **(error.headers or {})}
    )


async def _read_token_request(request: Request) -> OAuthTokenRequest:
    """The token request as a form (RFC 6749) or JSON; anything malformed is `invalid_request`."""
    content_type = request.headers.get('content-type', '').split(';')[0].strip().lower()
    try:
        if content_type == 'application/json':
            payload = await request.json()
        else:
            payload = {key: value for key, value in (await request.form()).items() if isinstance(value, str)}
        if not isinstance(payload, dict):
            raise TypeError('The body must be an object')
        return OAuthTokenRequest.model_validate(payload)
    except (TypeError, ValueError, ValidationError) as e:
        raise OAuthError(OAuthErrorCode.INVALID_REQUEST, 'Malformed token request') from e


@viewset(oauth_router)
class OAuthViewSet(BaseGenericViewSet[OAuthAuthorizationCode]):
    """
    OAuth 2.0 authorization code + PKCE (S256) for the Hearfolio apps. `authorize` serves the web app's consent
    page (cookie session, API error envelope); `token` and `revoke` serve the app and answer errors in the
    RFC 6749 §5.2 format `{error, error_description}`.
    """

    model = OAuthAuthorizationCode

    def get_permissions(self):
        if self.action == 'token':
            return []
        return [IsAuthenticated()]

    @action(methods=['GET'], path='authorize')
    async def authorize_info(self, data: Annotated[OAuthAuthorizeRequest, Query()]) -> OAuthAuthorizeInfoSchema:
        """Validate an authorization request for the consent screen (client name, device name)."""
        return OAuthService.validate_authorization(data, get_current_auth_state().auth_method)

    @action(methods=['POST'])
    async def authorize(self, data: OAuthAuthorizeRequest) -> OAuthAuthorizeResponse:
        """The signed-in user approves the app: a single-use code valid 60 s and the redirect URL."""
        info = OAuthService.validate_authorization(data, get_current_auth_state().auth_method)
        code, redirect_to = await OAuthService.authorize(self.user, data, info)
        return OAuthAuthorizeResponse(code=code, state=data.state, redirect_to=redirect_to)

    @action(methods=['POST'], openapi_extra=TOKEN_REQUEST_BODY)
    async def token(self, request: Request, response: Response) -> OAuthTokenResponse:
        """
        Exchange the code (`grant_type=authorization_code`, `code`, `code_verifier`, `redirect_uri`,
        `client_id`; form or JSON) for an API token named «Hearfolio · {device_name}». Errors use the RFC 6749
        body `{error, error_description}`: 400 `invalid_request | invalid_client | invalid_grant |
        unsupported_grant_type`, 429 `rate_limited`.
        """
        user, value = await OAuthService.exchange(await _read_token_request(request), client_ip(request))
        response.headers.update(NO_STORE)
        me = await MeSchema.for_user(user)
        return OAuthTokenResponse(access_token=value, user=me.user, organizations=me.organizations)

    @action(methods=['POST'], status_code=204)
    async def revoke(self) -> None:
        """Revoke the API token this request is authenticated with (`Authorization: Token ...`)."""
        auth_state = get_current_auth_state()
        await OAuthService.revoke(self.user, auth_state.auth_method, auth_state.api_token_id)
