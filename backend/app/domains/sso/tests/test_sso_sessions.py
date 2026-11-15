import asyncio
from datetime import timedelta

import pytest

from app.core.settings import settings
from app.core.utils.date_utils import utcnow
from app.domains.auth.models import RefreshSession
from app.domains.oauth.services.oauth_service import pkce_challenge
from app.domains.organization.models import OrganizationRole, OrganizationUser
from app.domains.sso.models import SsoLoginMode, SsoProvider, SsoSession, SsoSessionToken
from app.domains.sso.tests.conftest import CLIENT_SECRET, ISSUER, sso_sign_in
from app.domains.user.models import UserToken

TAGS = '/api/v1/tags'
PROVIDER = '/api/v1/sso-provider/current'


async def _member_with_sso_session(api_client, idp, sso_org, user_factory, **rules):
    organization, owner, provider = await sso_org(**rules)
    member = await user_factory(email='member@corp.example')
    await OrganizationUser.create(organization=organization, user=member)
    idp.add_user(sub='member', email=member.email, groups=['corex'])
    response = await sso_sign_in(api_client, idp, organization.key, 'member')
    assert response.status_code == 303
    return organization, owner, provider, member


async def _age_sessions(minutes: int) -> None:
    await SsoSession.all().update(validated_at=utcnow() - timedelta(minutes=minutes))


# «SSO ONLY»


@pytest.mark.asyncio
async def test_sso_only_organization_rejects_password_sessions(api_client, idp, sso_org, user_factory, auth_headers):
    organization, owner, _, member = await _member_with_sso_session(
        api_client, idp, sso_org, user_factory, login_mode=SsoLoginMode.SSO_ONLY
    )

    # The SSO session (cookies) opens the organization.
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200

    # A password session of the same member does not.
    password = await auth_headers(member, organization)
    denied = await api_client.get(TAGS, headers={**password, 'Cookie': ''})
    assert denied.status_code == 403
    assert denied.json()['error']['details'] == {'reason': 'sso_required', 'organization_key': organization.key}

    # Owners keep password access while the break-glass switch is on.
    owner_headers = await auth_headers(owner, organization)
    assert (await api_client.get(TAGS, headers={**owner_headers, 'Cookie': ''})).status_code == 200
    await SsoProvider.filter(organization=organization).update(owner_password_fallback=False)
    assert (await api_client.get(TAGS, headers={**owner_headers, 'Cookie': ''})).status_code == 403


@pytest.mark.asyncio
async def test_password_and_sso_mode_accepts_both(api_client, idp, sso_org, user_factory, auth_headers):
    organization, _, _, member = await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    headers = await auth_headers(member, organization)
    assert (await api_client.get(TAGS, headers={**headers, 'Cookie': ''})).status_code == 200


# REVALIDATION


@pytest.mark.asyncio
async def test_fresh_session_is_not_rechecked(api_client, idp, sso_org, user_factory):
    organization, _, _, _ = await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    idp.calls.clear()
    for _ in range(3):
        assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200
    assert idp.calls == []


@pytest.mark.asyncio
async def test_deactivated_user_loses_the_session_on_the_next_request_after_the_interval(
    api_client, idp, sso_org, user_factory
):
    organization, _, _, _ = await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    idp.users['member'].active = False

    # Within the interval nothing is asked.
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200

    await _age_sessions(11)
    response = await api_client.get('/api/v1/auth/me')

    assert response.status_code == 401
    session = await SsoSession.get()
    assert session.revoked_at is not None and session.revoke_reason == 'token_error'
    assert session.refresh_token_encrypted == ''
    assert not await RefreshSession.filter(family_id=session.family_id, revoked_at=None).exists()
    assert (await api_client.post('/api/v1/auth/refresh')).status_code == 401


@pytest.mark.asyncio
async def test_refresh_grant_rotates_and_keeps_an_active_user(api_client, idp, sso_org, user_factory):
    organization, _, _, _ = await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    before = (await SsoSession.get()).refresh_token_encrypted
    await _age_sessions(11)

    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200

    session = await SsoSession.get()
    assert session.revoked_at is None
    assert session.refresh_token_encrypted != before
    assert utcnow() - session.validated_at < timedelta(minutes=1)
    assert 'POST /api/v1/oidc/token' in idp.calls and 'GET /api/v1/oidc/userinfo' in idp.calls


@pytest.mark.asyncio
async def test_userinfo_fallback_without_refresh_token(api_client, idp, sso_org, user_factory):
    idp.issue_refresh_tokens = False
    organization, _, _, _ = await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    await _age_sessions(11)
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200

    idp.users['member'].active = False
    await _age_sessions(11)
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 401
    assert (await SsoSession.get()).revoke_reason == 'userinfo_unauthorized'


@pytest.mark.asyncio
async def test_expired_access_token_without_refresh_token_needs_a_new_sign_in_after_the_grace_period(
    api_client, idp, sso_org, user_factory
):
    idp.issue_refresh_tokens = False
    organization, _, _, _ = await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    await SsoSession.all().update(access_token_expires_at=utcnow() - timedelta(minutes=1))
    await _age_sessions(11)
    idp.calls.clear()

    # Not a verdict on the user: the session keeps working within the grace period, the provider is not asked.
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200
    assert idp.calls == []
    assert (await SsoSession.get()).revoked_at is None

    await _age_sessions(settings.sso_revalidate_grace_seconds // 60 + 1)
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 401
    assert (await SsoSession.get()).revoke_reason == 'reauth_required'


@pytest.mark.asyncio
async def test_concurrent_requests_refresh_once(api_client, idp, sso_org, user_factory):
    organization, _, _, _ = await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    await _age_sessions(11)
    idp.calls.clear()

    responses = await asyncio.gather(
        *(api_client.get(TAGS, headers={'Organization-Key': organization.key}) for _ in range(6))
    )

    assert [response.status_code for response in responses] == [200] * 6
    # Strict reuse detection at the provider: a second refresh with the same token would have ended the session.
    assert idp.calls.count('POST /api/v1/oidc/token') == 1
    session = await SsoSession.get()
    assert session.revoked_at is None and session.check_started_at is None
    assert idp.refresh_tokens  # the rotated token is the live one

    # The next check uses the stored (rotated) token, not the old one.
    await _age_sessions(11)
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200
    assert (await SsoSession.get()).revoked_at is None


@pytest.mark.asyncio
async def test_lost_group_ends_the_session(api_client, idp, sso_org, user_factory):
    organization, _, _, _ = await _member_with_sso_session(
        api_client, idp, sso_org, user_factory, required_groups=['corex']
    )
    idp.users['member'].groups = ['other']
    await _age_sessions(11)

    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 401
    assert (await SsoSession.get()).revoke_reason == 'rules_not_met'


@pytest.mark.asyncio
async def test_provider_down_keeps_the_session_within_the_grace_period_then_ends_it(
    api_client, idp, sso_org, user_factory
):
    organization, _, _, _ = await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    idp.down = True
    await _age_sessions(11)

    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200
    session = await SsoSession.get()
    assert session.revoked_at is None and session.check_started_at is None

    grace_minutes = settings.sso_revalidate_grace_seconds // 60
    await _age_sessions(grace_minutes + 1)
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 401
    assert (await SsoSession.get()).revoke_reason == 'provider_unavailable'


@pytest.mark.asyncio
async def test_one_check_in_flight_per_session(api_client, idp, sso_org, user_factory):
    organization, _, _, _ = await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    idp.users['member'].active = False
    await _age_sessions(11)
    # Another process is checking this session right now.
    await SsoSession.all().update(check_started_at=utcnow())
    idp.calls.clear()

    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200
    assert idp.calls == []


@pytest.mark.asyncio
async def test_org_level_interval(api_client, idp, sso_org, user_factory):
    organization, _, _, _ = await _member_with_sso_session(
        api_client, idp, sso_org, user_factory, revalidate_interval_minutes=30
    )
    idp.users['member'].active = False
    await _age_sessions(11)
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 200
    await _age_sessions(31)
    assert (await api_client.get(TAGS, headers={'Organization-Key': organization.key})).status_code == 401


@pytest.mark.asyncio
async def test_logout_ends_the_sso_session(api_client, idp, sso_org, user_factory):
    await _member_with_sso_session(api_client, idp, sso_org, user_factory)
    assert (await api_client.post('/api/v1/auth/logout')).status_code == 204
    assert (await SsoSession.get()).revoke_reason == 'logout'


# APP TOKENS (OAuth for the desktop/mobile app)


@pytest.mark.asyncio
async def test_app_token_approved_from_an_sso_session_ends_with_it(api_client, idp, sso_org, user_factory):
    organization, _, _, _ = await _member_with_sso_session(
        api_client, idp, sso_org, user_factory, login_mode=SsoLoginMode.SSO_ONLY
    )
    verifier = 'v' * 64
    approve = await api_client.post(
        '/api/v1/oauth/authorize',
        json={
            'client_id': 'hearfolio-app',
            'redirect_uri': 'hearfolio://oauth/callback',
            'code_challenge': pkce_challenge(verifier),
            'code_challenge_method': 'S256',
            'device_name': 'MacBook',
        },
    )
    assert approve.status_code == 200, approve.text
    exchanged = await api_client.post(
        '/api/v1/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': approve.json()['code'],
            'code_verifier': verifier,
            'redirect_uri': 'hearfolio://oauth/callback',
            'client_id': 'hearfolio-app',
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    app_headers = {
        'Authorization': f'Token {exchanged.json()["access_token"]}',
        'Organization-Key': organization.key,
        'Cookie': '',
    }
    assert await SsoSessionToken.exists()
    # The app token counts as an SSO session for «SSO only».
    assert (await api_client.get(TAGS, headers=app_headers)).status_code == 200

    idp.users['member'].active = False
    await _age_sessions(11)
    assert (await api_client.get(TAGS, headers=app_headers)).status_code == 401
    assert not await UserToken.exists()


# PROVIDER SETTINGS (org admins)


@pytest.mark.asyncio
async def test_admin_connects_a_provider_and_the_secret_never_leaves(
    api_client, idp, organization_factory, user_factory, auth_headers
):
    owner = await user_factory()
    organization = await organization_factory()
    await OrganizationUser.create(organization=organization, user=owner, role=OrganizationRole.OWNER)
    headers = {**await auth_headers(owner, organization), 'Cookie': ''}

    empty = await api_client.get(PROVIDER, headers=headers)
    assert empty.status_code == 200
    assert empty.json()['provider'] is None
    assert empty.json()['redirect_uri'] == f'http://test/api/v1/sso/callback/{organization.id}'
    assert empty.json()['login_url'] == f'http://test/sso/{organization.key}'

    incomplete = await api_client.patch(PROVIDER, headers=headers, json={'issuer': ISSUER})
    assert incomplete.status_code == 400

    saved = await api_client.patch(
        PROVIDER,
        headers=headers,
        json={
            'issuer': ISSUER + '/',
            'client_id': 'hearfolio-client',
            'client_secret': CLIENT_SECRET,
            'button_label': 'Войти через Example',
            'scopes': ['email', 'openid', 'groups'],
        },
    )
    assert saved.status_code == 200, saved.text
    assert CLIENT_SECRET not in saved.text
    body = saved.json()['provider']
    assert body['issuer'] == ISSUER
    assert body['has_client_secret'] is True
    assert body['scopes'] == ['openid', 'email', 'groups']
    assert 'client_secret' not in body and 'client_secret_encrypted' not in body
    assert CLIENT_SECRET not in (await api_client.get(PROVIDER, headers=headers)).text
    stored = await SsoProvider.get(organization=organization)
    assert stored.client_secret_encrypted and CLIENT_SECRET not in stored.client_secret_encrypted

    tested = await api_client.post('/api/v1/sso-provider/test', headers=headers, json={})
    assert tested.status_code == 200
    assert tested.json()['ok'] is True, tested.json()
    assert CLIENT_SECRET not in tested.text

    wrong = await api_client.post('/api/v1/sso-provider/test', headers=headers, json={'client_secret': 'nope'})
    assert wrong.json()['ok'] is False

    removed = await api_client.delete(PROVIDER, headers=headers)
    assert removed.status_code == 204
    assert not await SsoProvider.exists()


@pytest.mark.asyncio
async def test_members_cannot_see_provider_settings(api_client, idp, sso_org, user_factory, auth_headers):
    organization, _, _ = await sso_org()
    member = await user_factory()
    await OrganizationUser.create(organization=organization, user=member)
    headers = {**await auth_headers(member, organization), 'Cookie': ''}
    assert (await api_client.get(PROVIDER, headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_changing_issuer_or_client_needs_the_secret_again(api_client, idp, sso_org, auth_headers):
    organization, owner, _ = await sso_org()
    headers = {**await auth_headers(owner, organization), 'Cookie': ''}
    response = await api_client.patch(PROVIDER, headers=headers, json={'client_id': 'another'})
    assert response.status_code == 400
    assert response.json()['error']['details']['reason'] == 'client_secret_required'


@pytest.mark.asyncio
async def test_sso_only_needs_proof_or_owner_break_glass(api_client, idp, sso_org, user_factory, auth_headers):
    organization, owner, _ = await sso_org()
    admin = await user_factory(email='admin@corp.example')
    await OrganizationUser.create(organization=organization, user=admin, role=OrganizationRole.ADMIN)

    admin_password = {**await auth_headers(admin, organization), 'Cookie': ''}
    locked = await api_client.patch(PROVIDER, headers=admin_password, json={'login_mode': 'sso_only'})
    assert locked.status_code == 400
    assert locked.json()['error']['details']['reason'] == 'sso_session_required'

    # An admin who signed in through the provider proves it works.
    idp.add_user(sub='admin', email=admin.email)
    await sso_sign_in(api_client, idp, organization.key, 'admin')
    proven = await api_client.patch(
        PROVIDER, headers={'Organization-Key': organization.key}, json={'login_mode': 'sso_only'}
    )
    assert proven.status_code == 200, proven.text

    # The owner with break-glass on may switch it without an SSO session.
    owner_password = {**await auth_headers(owner, organization), 'Cookie': ''}
    assert (
        await api_client.patch(PROVIDER, headers=owner_password, json={'revalidate_interval_minutes': 15})
    ).status_code == 200
    assert (
        await api_client.patch(PROVIDER, headers=owner_password, json={'owner_password_fallback': False})
    ).status_code == 400

    # With an SSO session the owner turns break-glass off; other rules stay editable afterwards.
    idp.add_user(sub='owner', email=owner.email)
    await sso_sign_in(api_client, idp, organization.key, 'owner')
    sso_headers = {'Organization-Key': organization.key}
    assert (
        await api_client.patch(PROVIDER, headers=sso_headers, json={'owner_password_fallback': False})
    ).status_code == 200
    assert (await api_client.patch(PROVIDER, headers=sso_headers, json={'join_policy': 'provider'})).status_code == 200


@pytest.mark.asyncio
async def test_superuser_password_session_edits_sso_only_rules(api_client, idp, sso_org, user_factory, auth_headers):
    organization, _, _ = await sso_org(login_mode=SsoLoginMode.SSO_ONLY, owner_password_fallback=False)
    superuser = await user_factory(is_superuser=True)
    await OrganizationUser.create(organization=organization, user=superuser)
    headers = {**await auth_headers(superuser, organization), 'Cookie': ''}
    response = await api_client.patch(PROVIDER, headers=headers, json={'join_policy': 'provider'})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_owner_cannot_be_the_default_role(api_client, idp, sso_org, auth_headers):
    organization, owner, _ = await sso_org()
    headers = {**await auth_headers(owner, organization), 'Cookie': ''}
    response = await api_client.patch(PROVIDER, headers=headers, json={'default_role': 'owner'})
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('issuer', 'reason'),
    [
        ('http://idp.example.com', 'insecure_url'),
        ('https://10.0.0.5', 'private_url'),
        ('https://169.254.169.254', 'private_url'),
    ],
)
async def test_discovery_is_ssrf_guarded(
    api_client, idp, organization_factory, user_factory, auth_headers, issuer, reason, monkeypatch
):
    monkeypatch.setattr(settings, 'debug', False)
    owner = await user_factory()
    organization = await organization_factory()
    await OrganizationUser.create(organization=organization, user=owner, role=OrganizationRole.OWNER)
    headers = {**await auth_headers(owner, organization), 'Cookie': ''}

    response = await api_client.patch(
        PROVIDER, headers=headers, json={'issuer': issuer, 'client_id': 'c', 'client_secret': 's'}
    )

    assert response.status_code == 400
    assert response.json()['error']['details']['reason'] == reason
    assert idp.calls == []
