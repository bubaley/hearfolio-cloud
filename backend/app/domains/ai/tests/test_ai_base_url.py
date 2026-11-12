import httpx2
import pytest

from app.core.settings import settings as app_settings
from app.domains.ai.models import OrganizationSettings
from app.domains.ai.services.openrouter_client import OpenRouterClient
from app.domains.ai.tests.fakes import FakeProvider
from app.domains.organization.models import OrganizationRole, OrganizationUser

SECRET = 'sk-or-v1-0123456789abcdef'

SETTINGS_URL = '/api/v1/ai-settings/current'
TEST_URL = '/api/v1/ai-settings/test'


@pytest.fixture
def provider(monkeypatch) -> FakeProvider:
    fake = FakeProvider()
    monkeypatch.setattr(OpenRouterClient, 'default_transport', fake.transport)
    return fake


@pytest.fixture
async def team(user_factory, organization_factory):
    admin = await user_factory()
    organization = await organization_factory()
    await OrganizationUser.create(organization=organization, user=admin, role=OrganizationRole.ADMIN)
    return organization, admin, None


@pytest.mark.asyncio
async def test_moving_the_base_url_requires_the_key_again(api_client, auth_headers, team, provider):
    organization, admin, _ = team
    headers = await auth_headers(admin, organization)
    await api_client.patch(SETTINGS_URL, headers=headers, json={'openrouter_api_key': SECRET})

    response = await api_client.patch(
        SETTINGS_URL, headers=headers, json={'openrouter_base_url': 'https://evil.example.com'}
    )
    assert response.status_code == 400
    assert response.json()['error']['message'] == 'При смене адреса API укажите ключ заново'
    assert response.json()['error']['details']['reason'] == 'api_key_required'
    stored = await OrganizationSettings.get(organization_id=organization.id)
    assert stored.openrouter_base_url == 'https://openrouter.ai/api/v1'

    # Re-sending the same URL is not a move.
    response = await api_client.patch(
        SETTINGS_URL, headers=headers, json={'openrouter_base_url': 'https://openrouter.ai/api/v1/'}
    )
    assert response.status_code == 200
    # A move together with the key is fine.
    other_key = 'sk-other-0123456789'
    response = await api_client.patch(
        SETTINGS_URL,
        headers=headers,
        json={'openrouter_base_url': 'https://llm.example.com/v1', 'openrouter_api_key': other_key},
    )
    assert response.status_code == 200
    assert response.json()['openrouter_base_url'] == 'https://llm.example.com/v1'

    # The connection test never sends the saved key to another host.
    provider.add('/key', httpx2.Response(200, json={'data': {}}))
    response = await api_client.post(
        TEST_URL, headers=headers, json={'openrouter_base_url': 'https://evil.example.com'}
    )
    assert response.json() == {'ok': False, 'message': 'Для нового адреса API укажите ключ'}
    assert provider.calls('/key') == []
    response = await api_client.post(TEST_URL, headers=headers, json={})
    assert response.json()['ok'] is True
    assert provider.calls('/key')[0].headers['authorization'] == f'Bearer {other_key}'


@pytest.mark.asyncio
async def test_private_base_urls_are_rejected_unless_allowed(api_client, auth_headers, team, monkeypatch):
    organization, admin, _ = team
    headers = await auth_headers(admin, organization)
    for base_url in (
        'http://127.0.0.1:8080/v1',
        'http://localhost/v1',
        'http://169.254.169.254/latest',
        'http://[::1]/v1',
        'http://10.1.2.3/v1',
        'https://gateway.internal.test/v1',
    ):
        response = await api_client.patch(SETTINGS_URL, headers=headers, json={'openrouter_base_url': base_url})
        assert response.status_code == 400, base_url
        assert response.json()['error']['details']['reason'] == 'private_base_url'
        response = await api_client.post(
            TEST_URL, headers=headers, json={'openrouter_base_url': base_url, 'openrouter_api_key': SECRET}
        )
        assert response.status_code == 400, base_url

    monkeypatch.setattr(app_settings, 'ai_allow_private_base_urls', True)
    response = await api_client.patch(
        SETTINGS_URL, headers=headers, json={'openrouter_base_url': 'https://gateway.internal.test/v1'}
    )
    assert response.status_code == 200
