from starlette.requests import HTTPConnection

from app.core.settings import settings


def client_ip(connection: HTTPConnection) -> str:
    # Behind Caddy this is the real client only when uvicorn runs with --proxy-headers.
    return connection.client.host if connection.client else 'unknown'


def public_base_url(connection: HTTPConnection) -> str:
    """`PUBLIC_URL`, else the scheme and host the request came to; no trailing slash."""
    if settings.public_url:
        return settings.public_url.rstrip('/')
    return str(connection.base_url).rstrip('/')
