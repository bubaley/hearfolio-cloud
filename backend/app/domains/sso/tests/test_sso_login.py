from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.domains.auth.models import RefreshSession
from app.domains.auth.transport import ACCESS_COOKIE
from app.domains.organization.models import OrganizationRole, OrganizationUser
from app.domains.sso.models import SsoIdentity, SsoJoinPolicy, SsoLoginRequest, SsoSession
from app.domains.sso.tests.conftest import sso_sign_in
from app.domains.user.models import User


def _location(response) -> tuple[str, dict[str, str]]:
    assert response.status_code == 303, response.text
    parts = urlsplit(response.headers['location'])
    return parts.path, {key: values[0] for key, values in parse_qs(parts.query).items()}


def _sso_error(response) -> str:
    path, params = _location(response)
    assert path.startswith('/sso/') or path == '/settings/profile'
    assert ACCESS_COOKIE not in response.cookies
    return params['sso_error']


@pytest.mark.asyncio
async def test_existing_member_signs_in_and_is_linked_by_verified_email(api_client, idp, sso_org, user_factory):
    organization, _, provider = await sso_org()
    member = await user_factory(email='ivan@corp.example')
    await OrganizationUser.create(organization=organization, user=member)
    idp.add_user(sub='u-1', email='Ivan@corp.example', groups=['corex'])

    response = await sso_sign_in(api_client, idp, organization.key, 'u-1')

    path, _ = _location(response)
    assert path == '/home'
    assert ACCESS_COOKIE in response.cookies
    me = await api_client.get('/api/v1/auth/me')
    assert me.json()['user']['id'] == str(member.id)
    identity = await SsoIdentity.get(provider=provider, subject='u-1')
    assert identity.user_id == member.id
    assert identity.groups == ['corex']
    session = await SsoSession.get(identity=identity)
    assert session.refresh_token_encrypted and session.revoked_at is None
    # PKCE + nonce + state were sent; the request is single use.
    assert await SsoLoginRequest.filter(used_at__isnull=False).count() == 1


@pytest.mark.asyncio
async def test_second_sign_in_finds_the_user_by_sub_even_when_the_email_changed(api_client, idp, sso_org, user_factory):
    organization, _, _ = await sso_org()
    member = await user_factory(email='a@corp.example')
    await OrganizationUser.create(organization=organization, user=member)
    fake = idp.add_user(sub='u-1', email='a@corp.example')
    await sso_sign_in(api_client, idp, organization.key, 'u-1')
    fake.email = 'renamed@corp.example'
    api_client.cookies.clear()

    response = await sso_sign_in(api_client, idp, organization.key, 'u-1')

    assert _location(response)[0] == '/home'
    assert (await api_client.get('/api/v1/auth/me')).json()['user']['id'] == str(member.id)


@pytest.mark.asyncio
async def test_redirect_back_to_the_app_consent_page(api_client, idp, sso_org, user_factory):
    organization, owner, _ = await sso_org()
    idp.add_user(sub='owner', email=owner.email)
    target = '/oauth/authorize?client_id=hearfolio-app&state=x'

    response = await sso_sign_in(api_client, idp, organization.key, 'owner', redirect=target)

    assert response.headers['location'].endswith(target)


@pytest.mark.asyncio
@pytest.mark.parametrize('redirect', ['//evil.example/x', 'https://evil.example', '/api/v1/auth/logout'])
async def test_unsafe_redirects_fall_back_to_home(api_client, idp, sso_org, redirect):
    organization, owner, _ = await sso_org()
    idp.add_user(sub='owner', email=owner.email)

    response = await sso_sign_in(api_client, idp, organization.key, 'owner', redirect=redirect)

    assert _location(response)[0] == '/home'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('overrides', 'reason'),
    [
        ({'iss': 'https://other.example.com'}, 'invalid_issuer'),
        ({'aud': 'someone-else'}, 'invalid_audience'),
        ({'nonce': 'replayed'}, 'invalid_nonce'),
        ({'exp': 1_000_000}, 'expired_id_token'),
    ],
)
async def test_bad_id_token_claims_are_rejected(api_client, idp, sso_org, overrides, reason):
    organization, owner, _ = await sso_org()
    idp.add_user(sub='owner', email=owner.email)
    idp.id_token_overrides = overrides

    assert _sso_error(await sso_sign_in(api_client, idp, organization.key, 'owner')) == reason
    assert not await SsoIdentity.exists()


@pytest.mark.asyncio
async def test_id_token_signed_by_another_key_is_rejected(api_client, idp, sso_org):
    organization, owner, _ = await sso_org()
    idp.add_user(sub='owner', email=owner.email)
    idp.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assert _sso_error(await sso_sign_in(api_client, idp, organization.key, 'owner')) == 'invalid_signature'


@pytest.mark.asyncio
async def test_state_is_single_use_and_bound_to_the_browser(api_client, idp, sso_org):
    organization, owner, _ = await sso_org()
    idp.add_user(sub='owner', email=owner.email)
    started = await api_client.post('/api/v1/sso/start', json={'organization_key': organization.key})
    code, params = idp.authorize(started.json()['authorization_url'], 'owner')
    callback = urlsplit(params['redirect_uri']).path

    forged = await api_client.get(callback, params={'code': code, 'state': 'forged'})
    assert _sso_error(forged) == 'invalid_state'

    browser = api_client.cookies.get('sso_browser')
    api_client.cookies.clear()
    other_browser = await api_client.get(callback, params={'code': code, 'state': params['state']})
    assert _sso_error(other_browser) == 'browser_mismatch'

    api_client.cookies.set('sso_browser', browser or '', path='/api/v1/sso')
    replay = await api_client.get(callback, params={'code': code, 'state': params['state']})
    assert _sso_error(replay) == 'invalid_state'


@pytest.mark.asyncio
async def test_unverified_email_never_links_an_existing_account(api_client, idp, sso_org, user_factory):
    organization, _, _ = await sso_org()
    victim = await user_factory(email='victim@corp.example')
    await OrganizationUser.create(organization=organization, user=victim)
    idp.add_user(sub='attacker', email='victim@corp.example', email_verified=False)

    assert _sso_error(await sso_sign_in(api_client, idp, organization.key, 'attacker')) == 'email_not_verified'
    assert not await SsoIdentity.exists()


@pytest.mark.asyncio
async def test_invite_only_organization_does_not_let_strangers_in(api_client, idp, sso_org):
    organization, _, _ = await sso_org()
    idp.add_user(sub='stranger', email='stranger@corp.example')

    assert _sso_error(await sso_sign_in(api_client, idp, organization.key, 'stranger')) == 'not_member'
    assert not await User.exists(email='stranger@corp.example')


@pytest.mark.asyncio
async def test_open_organization_creates_the_account_and_joins_with_the_default_role(api_client, idp, sso_org):
    organization, _, provider = await sso_org(
        join_policy=SsoJoinPolicy.PROVIDER,
        allowed_email_domains=['corp.example'],
        required_groups=['corex:dev'],
        default_role=OrganizationRole.ADMIN,
    )
    idp.add_user(sub='new', email='new@corp.example', name='Анна Смирнова', groups=['corex', 'corex:dev'])

    response = await sso_sign_in(api_client, idp, organization.key, 'new')

    assert _location(response)[0] == '/home'
    user = await User.get(email='new@corp.example')
    assert (user.first_name, user.last_name) == ('Анна', 'Смирнова')
    membership = await OrganizationUser.get(organization=organization, user=user)
    assert membership.role == OrganizationRole.ADMIN
    identity = await SsoIdentity.get(provider=provider, user=user)
    assert identity.created_user is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('fake_user', 'reason'),
    [
        ({'email': 'new@other.example', 'groups': ['corex:dev']}, 'domain_not_allowed'),
        ({'email': 'new@corp.example', 'email_verified': False, 'groups': ['corex:dev']}, 'domain_not_allowed'),
        ({'email': 'new@corp.example', 'groups': ['corex']}, 'group_required'),
    ],
)
async def test_open_organization_rules(api_client, idp, sso_org, fake_user, reason):
    organization, _, _ = await sso_org(
        join_policy=SsoJoinPolicy.PROVIDER, allowed_email_domains=['corp.example'], required_groups=['corex:dev']
    )
    idp.add_user(sub='new', **fake_user)

    assert _sso_error(await sso_sign_in(api_client, idp, organization.key, 'new')) == reason
    assert not await User.exists(email=fake_user['email'])


@pytest.mark.asyncio
async def test_start_by_email_domain(api_client, idp, sso_org):
    organization, _, _ = await sso_org(allowed_email_domains=['corp.example'])

    started = await api_client.post('/api/v1/sso/start', json={'email': 'someone@Corp.example'})
    assert started.status_code == 200
    params = parse_qs(urlsplit(started.json()['authorization_url']).query)
    assert params['code_challenge_method'] == ['S256']
    assert params['login_hint'] == ['someone@Corp.example']
    assert str(organization.id) in params['redirect_uri'][0]

    unknown = await api_client.post('/api/v1/sso/start', json={'email': 'someone@nowhere.example'})
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_public_organization_preview(api_client, idp, sso_org, organization_factory):
    organization, _, _ = await sso_org()
    plain = await organization_factory()

    preview = await api_client.get(f'/api/v1/sso/organizations/{organization.key}')
    assert preview.status_code == 200
    assert preview.json()['button_label'] == 'Войти через Example'
    assert (await api_client.get(f'/api/v1/sso/organizations/{plain.key}')).status_code == 404


@pytest.mark.asyncio
async def test_link_and_unlink_from_the_profile(api_client, idp, sso_org, user_factory, auth_headers):
    organization, _, provider = await sso_org()
    user = await user_factory(email='me@corp.example')
    await OrganizationUser.create(organization=organization, user=user)
    login = await api_client.post('/api/v1/auth/login', json={'email': user.email, 'password': 'test-password'})
    assert login.status_code == 200
    # A different email at the provider: linking from the profile proves both accounts.
    idp.add_user(sub='work', email='other@corp.example', email_verified=False)

    started = await api_client.post('/api/v1/sso/link', json={'organization_key': organization.key})
    assert started.status_code == 200
    code, params = idp.authorize(started.json()['authorization_url'], 'work')
    response = await api_client.get(
        urlsplit(params['redirect_uri']).path, params={'code': code, 'state': params['state']}
    )

    assert _location(response)[0] == '/settings/profile'
    listed = (await api_client.get('/api/v1/sso/identities')).json()
    assert [(item['organization_key'], item['is_only_sign_in']) for item in listed] == [(organization.key, False)]
    session = await SsoSession.get(provider=provider)

    unlinked = await api_client.delete(f'/api/v1/sso/identities/{listed[0]["id"]}')
    assert unlinked.status_code == 204, unlinked.text
    assert not await SsoIdentity.exists()
    # The SSO session ended with the link: its refresh family is revoked.
    assert not await RefreshSession.filter(family_id=session.family_id, revoked_at=None).exists()


@pytest.mark.asyncio
async def test_the_only_sign_in_cannot_be_unlinked(api_client, idp, sso_org):
    organization, _, _ = await sso_org(join_policy=SsoJoinPolicy.PROVIDER)
    idp.add_user(sub='new', email='new@corp.example')
    await sso_sign_in(api_client, idp, organization.key, 'new')
    identity = (await api_client.get('/api/v1/sso/identities')).json()[0]
    assert identity['is_only_sign_in'] is True

    response = await api_client.delete(f'/api/v1/sso/identities/{identity["id"]}')

    assert response.status_code == 409
    assert response.json()['error']['details']['reason'] == 'only_sign_in'
