"""
OpenID Connect relying-party calls: discovery, JWKS, token and userinfo endpoints, ID token validation. Standards
only (OIDC Core 1.0, Discovery 1.0, RFC 7636): nothing here knows a specific provider.

Every outgoing request is SSRF-guarded (`validate_url`): https only (http just for loopback while DEBUG is on), no
private/loopback/link-local targets unless SSO_ALLOW_PRIVATE_ISSUERS, no redirects, a timeout and a size limit.
"""

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import time
from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import quote, urlsplit

import httpx2
import jwt

from app.core.settings import settings

DISCOVERY_PATH = '/.well-known/openid-configuration'
SUPPORTED_SIGNING_ALGS = ('RS256', 'RS384', 'RS512', 'PS256', 'PS384', 'PS512', 'ES256', 'ES384', 'ES512')
LOOPBACK_HOSTS = frozenset({'localhost', '127.0.0.1', '::1'})
HOST_LOOKUP_TIMEOUT_SECONDS = 3.0
# Clock skew tolerated on `exp`/`iat`/`nbf`
CLOCK_LEEWAY_SECONDS = 60
METADATA_FIELDS = (
    'issuer',
    'authorization_endpoint',
    'token_endpoint',
    'userinfo_endpoint',
    'jwks_uri',
    'end_session_endpoint',
    'scopes_supported',
    'response_types_supported',
    'grant_types_supported',
    'id_token_signing_alg_values_supported',
    'token_endpoint_auth_methods_supported',
    'code_challenge_methods_supported',
    'claims_supported',
)


class OidcError(Exception):
    """
    A failed provider interaction. `reason` is a stable code (logs, `details.reason`, the callback redirect),
    `message` is shown to people (Russian). `transient`: the provider was unreachable or failed (5xx, timeout), so the
    result says nothing about the user. `oauth_error`: the RFC 6749 `error` the provider answered.
    """

    def __init__(self, reason: str, message: str, *, transient: bool = False, oauth_error: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.transient = transient
        self.oauth_error = oauth_error


@dataclass(frozen=True)
class HttpResult:
    status: int
    payload: Any


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def at_hash(access_token: str, alg: str) -> str:
    """OIDC Core §3.1.3.6: base64url of the left half of the access token hash (SHA-256/384/512 by the alg)."""
    digest = hashlib.new(f'sha{alg[2:]}', access_token.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b'=').decode('ascii')


def normalize_groups(value: Any) -> list[str]:
    """The `groups` claim as opaque strings (a single string counts as one group)."""
    return list(dict.fromkeys(item.strip() for item in _string_list(value) if item.strip()))


class OidcClient:
    # Tests install an `httpx2.MockTransport` here.
    transport: ClassVar[httpx2.AsyncBaseTransport | None] = None
    _jwks_cache: ClassVar[dict[str, tuple[float, dict[str, Any]]]] = {}

    # URL GUARD

    @staticmethod
    async def lookup_host(host: str) -> list[str]:
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(loop.getaddrinfo(host, None), timeout=HOST_LOOKUP_TIMEOUT_SECONDS)
        except OSError, TimeoutError:
            return []
        return [str(info[4][0]) for info in infos]

    @staticmethod
    def _is_loopback(host: str) -> bool:
        return host in LOOPBACK_HOSTS or host.endswith('.localhost')

    @classmethod
    async def validate_url(cls, url: str, label: str) -> str:
        parts = urlsplit(url)
        host = (parts.hostname or '').rstrip('.').lower()
        if parts.scheme not in ('https', 'http') or not host:
            raise OidcError('invalid_url', f'{label}: нужен полный адрес, начинающийся с https://')
        if parts.username or parts.password or parts.fragment:
            raise OidcError('invalid_url', f'{label}: адрес не должен содержать логин, пароль или #фрагмент')
        local_dev = cls._is_loopback(host) and settings.debug
        if parts.scheme == 'http' and not local_dev:
            raise OidcError('insecure_url', f'{label}: разрешены только адреса https://')
        if local_dev or settings.sso_allow_private_issuers:
            return url
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            addresses = await cls.lookup_host(host)
        if not addresses:
            raise OidcError('host_not_found', f'{label}: сервер {host} не найден', transient=True)
        for address in addresses:
            ip = ipaddress.ip_address(address.split('%', 1)[0])
            if not ip.is_global or ip.is_multicast:
                raise OidcError(
                    'private_url',
                    f'{label}: адрес указывает на внутреннюю сеть. Разрешите это на сервере (SSO_ALLOW_PRIVATE_ISSUERS)',
                )
        return url

    # HTTP

    @classmethod
    async def _request(
        cls,
        method: str,
        url: str,
        *,
        label: str,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        await cls.validate_url(url, label)
        limit = settings.sso_max_response_bytes
        body = bytearray()
        try:
            async with (
                httpx2.AsyncClient(
                    transport=cls.transport, timeout=settings.sso_http_timeout_seconds, follow_redirects=False
                ) as client,
                client.stream(
                    method, url, data=data, headers={'Accept': 'application/json', **(headers or {})}
                ) as response,
            ):
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise OidcError('response_too_large', f'{label}: провайдер прислал слишком большой ответ')
                status = response.status_code
        except httpx2.TimeoutException as e:
            raise OidcError('provider_unavailable', f'{label}: провайдер не ответил вовремя', transient=True) from e
        except httpx2.HTTPError as e:
            raise OidcError(
                'provider_unavailable', f'{label}: не удалось связаться с провайдером', transient=True
            ) from e
        try:
            payload = json.loads(body) if body else None
        except ValueError:
            payload = None
        return HttpResult(status=status, payload=payload)

    # DISCOVERY

    @classmethod
    async def discover(cls, issuer: str) -> dict[str, Any]:
        """Fetch and validate `{issuer}/.well-known/openid-configuration`; returns the fields Hearfolio uses."""
        issuer = issuer.strip()
        await cls.validate_url(issuer, 'Адрес провайдера')
        url = issuer.rstrip('/') + DISCOVERY_PATH
        result = await cls._request('GET', url, label='Discovery')
        if result.status >= 500:
            raise OidcError('discovery_failed', f'Discovery: провайдер ответил ошибкой {result.status}', transient=True)
        doc = result.payload
        if result.status != 200 or not isinstance(doc, dict):
            raise OidcError('discovery_failed', f'По адресу {url} нет настроек OpenID Connect (ответ {result.status})')
        if not isinstance(doc.get('issuer'), str) or doc['issuer'].rstrip('/') != issuer.rstrip('/'):
            raise OidcError(
                'issuer_mismatch',
                f'Провайдер называет себя «{doc.get("issuer")}», а не «{issuer}». Укажите адрес точно как issuer',
            )
        for field, label in (
            ('authorization_endpoint', 'Authorization endpoint'),
            ('token_endpoint', 'Token endpoint'),
            ('jwks_uri', 'JWKS'),
        ):
            if not isinstance(doc.get(field), str) or not doc[field]:
                raise OidcError('discovery_incomplete', f'В настройках провайдера нет {field}')
            await cls.validate_url(doc[field], label)
        if isinstance(doc.get('userinfo_endpoint'), str) and doc['userinfo_endpoint']:
            await cls.validate_url(doc['userinfo_endpoint'], 'Userinfo endpoint')
        response_types = doc.get('response_types_supported')
        if isinstance(response_types, list) and 'code' not in response_types:
            raise OidcError('unsupported_provider', 'Провайдер не поддерживает Authorization Code (response_type=code)')
        if not cls.signing_algs(doc):
            raise OidcError(
                'unsupported_provider',
                'Провайдер подписывает ID-токены алгоритмом, который не поддерживается (нужен RS256)',
            )
        pkce = doc.get('code_challenge_methods_supported')
        if isinstance(pkce, list) and 'S256' not in pkce:
            raise OidcError('unsupported_provider', 'Провайдер не поддерживает PKCE S256')
        cls.auth_method(doc)
        return {field: doc[field] for field in METADATA_FIELDS if field in doc}

    @staticmethod
    def signing_algs(metadata: dict[str, Any]) -> list[str]:
        declared = _string_list(metadata.get('id_token_signing_alg_values_supported')) or ['RS256']
        return [alg for alg in declared if alg in SUPPORTED_SIGNING_ALGS]

    @staticmethod
    def auth_method(metadata: dict[str, Any]) -> str:
        # RFC 8414: without the field the default is client_secret_basic.
        methods = _string_list(metadata.get('token_endpoint_auth_methods_supported')) or ['client_secret_basic']
        for method in ('client_secret_basic', 'client_secret_post'):
            if method in methods:
                return method
        raise OidcError(
            'unsupported_provider',
            'Провайдер не принимает client secret (нужен client_secret_basic или client_secret_post)',
        )

    # JWKS AND ID TOKENS

    @classmethod
    async def jwks(cls, jwks_uri: str, *, refresh: bool = False) -> dict[str, Any]:
        cached = cls._jwks_cache.get(jwks_uri)
        if cached and not refresh and time.monotonic() - cached[0] < settings.sso_jwks_cache_seconds:
            return cached[1]
        result = await cls._request('GET', jwks_uri, label='JWKS')
        doc = result.payload
        if result.status != 200 or not isinstance(doc, dict) or not isinstance(doc.get('keys'), list):
            raise OidcError(
                'jwks_failed',
                f'JWKS: провайдер не отдал ключи подписи (ответ {result.status})',
                transient=result.status >= 500,
            )
        cls._jwks_cache[jwks_uri] = (time.monotonic(), doc)
        return doc

    @staticmethod
    def _find_key(jwks: dict[str, Any], kid: str | None, alg: str) -> Any | None:
        candidates = [
            key
            for key in jwks.get('keys', [])
            if isinstance(key, dict) and key.get('use', 'sig') == 'sig' and (kid is None or key.get('kid') == kid)
        ]
        if kid is None and len(candidates) != 1:
            return None
        for candidate in candidates:
            try:
                return jwt.PyJWK(candidate, algorithm=alg).key
            except jwt.PyJWTError, ValueError, TypeError:
                continue
        return None

    @classmethod
    async def _signing_key(cls, jwks_uri: str, kid: str | None, alg: str) -> Any:
        key = cls._find_key(await cls.jwks(jwks_uri), kid, alg)
        if key is None:
            # Key rotation: an unknown kid refetches the set once.
            key = cls._find_key(await cls.jwks(jwks_uri, refresh=True), kid, alg)
        if key is None:
            raise OidcError('invalid_signature', 'ID-токен подписан неизвестным ключом')
        return key

    @classmethod
    async def validate_id_token(
        cls,
        metadata: dict[str, Any],
        client_id: str,
        token: str,
        *,
        nonce: str | None,
        expected_subject: str | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """
        Signature (JWKS), `iss`, `aud` (+`azp`), `exp`, `iat`, `nonce` when given, `sub` when expected, `at_hash`
        when the token carries one and the access token is known.
        """
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise OidcError('invalid_id_token', 'Провайдер вернул некорректный ID-токен') from e
        alg = header.get('alg')
        if not isinstance(alg, str) or alg not in cls.signing_algs(metadata):
            raise OidcError('invalid_id_token', f'ID-токен подписан недопустимым алгоритмом ({alg})')
        kid = header.get('kid') if isinstance(header.get('kid'), str) else None
        key = await cls._signing_key(metadata['jwks_uri'], kid, alg)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[alg],
                audience=client_id,
                issuer=metadata['issuer'],
                leeway=CLOCK_LEEWAY_SECONDS,
                options={'require': ['iss', 'sub', 'aud', 'exp', 'iat']},
            )
        except jwt.InvalidSignatureError as e:
            raise OidcError('invalid_signature', 'Подпись ID-токена не прошла проверку') from e
        except jwt.ExpiredSignatureError as e:
            raise OidcError('expired_id_token', 'Срок действия ID-токена истёк') from e
        except jwt.InvalidAudienceError as e:
            raise OidcError('invalid_audience', 'ID-токен выдан другому приложению (aud)') from e
        except jwt.InvalidIssuerError as e:
            raise OidcError('invalid_issuer', 'ID-токен выдан другим провайдером (iss)') from e
        except jwt.PyJWTError as e:
            raise OidcError('invalid_id_token', 'Провайдер вернул некорректный ID-токен') from e
        audience = claims.get('aud')
        if isinstance(audience, list) and len(audience) > 1 and claims.get('azp') != client_id:
            raise OidcError('invalid_audience', 'ID-токен выдан другому приложению (azp)')
        if not isinstance(claims.get('sub'), str) or not claims['sub']:
            raise OidcError('invalid_id_token', 'В ID-токене нет идентификатора пользователя (sub)')
        if nonce is not None and not hmac.compare_digest(str(claims.get('nonce', '')), nonce):
            raise OidcError('invalid_nonce', 'ID-токен не относится к этому входу (nonce)')
        if expected_subject is not None and claims['sub'] != expected_subject:
            raise OidcError('subject_mismatch', 'Провайдер вернул другого пользователя')
        token_hash = claims.get('at_hash')
        if (
            access_token is not None
            and isinstance(token_hash, str)
            and not hmac.compare_digest(token_hash, at_hash(access_token, alg))
        ):
            raise OidcError('invalid_id_token', 'ID-токен не относится к выданному access token (at_hash)')
        return claims

    # TOKEN AND USERINFO ENDPOINTS

    @classmethod
    def _client_auth(
        cls, metadata: dict[str, Any], client_id: str, client_secret: str, form: dict[str, str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        if cls.auth_method(metadata) == 'client_secret_basic':
            # RFC 6749 §2.3.1: both parts are form-urlencoded before base64.
            raw = f'{quote(client_id, safe="")}:{quote(client_secret, safe="")}'
            return {'Authorization': f'Basic {base64.b64encode(raw.encode()).decode()}'}, form
        return {}, {**form, 'client_id': client_id, 'client_secret': client_secret}

    @classmethod
    async def token_request(
        cls, metadata: dict[str, Any], client_id: str, client_secret: str, form: dict[str, str]
    ) -> dict[str, Any]:
        headers, data = cls._client_auth(metadata, client_id, client_secret, form)
        result = await cls._request(
            'POST', metadata['token_endpoint'], label='Token endpoint', data=data, headers=headers
        )
        payload = result.payload if isinstance(result.payload, dict) else {}
        if result.status == 200 and isinstance(payload.get('access_token'), str):
            return payload
        error = payload.get('error') if isinstance(payload.get('error'), str) else None
        transient = result.status >= 500 or result.status == 429
        if error == 'invalid_client' or result.status == 401:
            message = 'Провайдер не принял client id или секрет'
            error = error or 'invalid_client'
        elif error == 'invalid_grant':
            message = 'Провайдер отклонил вход: код или сеанс больше не действует'
        elif transient:
            message = f'Token endpoint: провайдер ответил ошибкой {result.status}'
        else:
            message = f'Token endpoint: провайдер отклонил запрос ({error or result.status})'
        raise OidcError('token_error', message, transient=transient, oauth_error=error)

    @classmethod
    async def userinfo(cls, metadata: dict[str, Any], access_token: str) -> dict[str, Any]:
        result = await cls._request(
            'GET',
            metadata['userinfo_endpoint'],
            label='Userinfo endpoint',
            headers={'Authorization': f'Bearer {access_token}'},
        )
        if result.status == 200 and isinstance(result.payload, dict):
            return result.payload
        if result.status in (401, 403):
            raise OidcError('userinfo_unauthorized', 'Провайдер больше не принимает этот сеанс')
        raise OidcError(
            'userinfo_failed',
            f'Userinfo endpoint: провайдер ответил ошибкой {result.status}',
            transient=result.status >= 500 or result.status == 429,
        )
