"""`GET /.well-known/hearfolio`: how a Hearfolio app discovers and checks a server before connecting."""

from typing import Literal

from fastapi import APIRouter, Request

from app.core.models import BaseSchema
from app.core.openapi import ERROR_RESPONSES
from app.core.settings import settings
from app.core.utils.request_utils import public_base_url

API_VERSION = 1

# Mounted at the root by `main.py` (not under /api/v1); Caddy routes `/.well-known/hearfolio` to the API.
well_known_router = APIRouter(prefix='/.well-known', tags=['well-known'], responses=ERROR_RESPONSES)


class OAuthEndpointsSchema(BaseSchema):
    authorize_url: str
    token_url: str
    revoke_url: str


class UploadLimitsSchema(BaseSchema):
    multipart_threshold_bytes: int
    part_size_bytes: int


class HearfolioDiscoverySchema(BaseSchema):
    product: Literal['hearfolio'] = 'hearfolio'
    name: str
    server_version: str
    api_version: int
    min_app_version: str
    oauth: OAuthEndpointsSchema
    upload: UploadLimitsSchema
    # Deleted recordings stay restorable («Корзина») this many days, then they and their audio are purged
    recording_purge_after_days: int


@well_known_router.get('/hearfolio')
async def hearfolio(request: Request) -> HearfolioDiscoverySchema:
    """Server identity, versions, OAuth endpoints, upload limits and trash retention. Public."""
    base_url = public_base_url(request)
    return HearfolioDiscoverySchema(
        name=settings.instance_name,
        server_version=settings.app_version,
        api_version=API_VERSION,
        min_app_version=settings.min_app_version,
        oauth=OAuthEndpointsSchema(
            # The consent page of the web app; the API endpoints below are what the app calls itself.
            authorize_url=f'{base_url}/oauth/authorize',
            token_url=f'{base_url}/api/v1/oauth/token',
            revoke_url=f'{base_url}/api/v1/oauth/revoke',
        ),
        upload=UploadLimitsSchema(
            multipart_threshold_bytes=settings.upload_multipart_threshold_bytes,
            part_size_bytes=settings.upload_part_size_bytes,
        ),
        recording_purge_after_days=settings.recording_purge_after_days,
    )
