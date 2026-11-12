from collections.abc import Iterator

import httpx2
import pytest

from app.domains.ai.models import OrganizationSettings, SummaryTemplate
from app.domains.ai.services.model_catalog_service import ModelCatalogService
from app.domains.ai.services.openrouter_client import OpenRouterClient
from app.domains.ai.services.organization_settings_service import OrganizationSettingsService
from app.domains.ai.services.transcription_engine import TranscriptionMode
from app.domains.ai.tests.fakes import FakeProvider, error_reply
from app.domains.organization.models import Organization, OrganizationRole, OrganizationUser

SECRET = 'sk-or-v1-0123456789abcdef'
CATALOG = {
    'data': [
        {
            'id': 'google/gemini-2.5-flash',
            'name': 'Google: Gemini 2.5 Flash',
            'context_length': 1048576,
            'top_provider': {'max_completion_tokens': 65535},
            'pricing': {'prompt': '0.0000003', 'completion': '0.0000025'},
            'architecture': {'input_modalities': ['text', 'image', 'audio'], 'output_modalities': ['text']},
        },
        {
            'id': 'anthropic/claude-sonnet',
            'name': 'Anthropic: Claude Sonnet',
            'architecture': {'input_modalities': ['text', 'image'], 'output_modalities': ['text']},
        },
        {'id': 'image/gen', 'architecture': {'input_modalities': ['text'], 'output_modalities': ['image']}},
        {'name': 'no id'},
    ]
}
STT_CATALOG = {
    'data': [
        {
            'id': 'openai/whisper-large',
            'name': 'Whisper Large',
            'architecture': {'input_modalities': ['audio'], 'output_modalities': ['transcription']},
        }
    ]
}


@pytest.fixture
def provider(monkeypatch) -> Iterator[FakeProvider]:
    def models(request: httpx2.Request) -> httpx2.Response:
        if request.url.params.get('output_modalities') == 'transcription':
            return httpx2.Response(200, json=STT_CATALOG)
        return httpx2.Response(200, json=CATALOG)

    fake = FakeProvider().add('/models', models)
    monkeypatch.setattr(OpenRouterClient, 'default_transport', fake.transport)
    ModelCatalogService.clear_memory_cache()
    yield fake
    ModelCatalogService.clear_memory_cache()


@pytest.fixture
async def team(user_factory, organization_factory):
    admin = await user_factory()
    member = await user_factory()
    organization = await organization_factory(members=(member,))
    await OrganizationUser.create(organization=organization, user=admin, role=OrganizationRole.ADMIN)
    return organization, admin, member


@pytest.mark.asyncio
async def test_new_organization_gets_settings_and_default_templates(organization_factory):
    organization = await organization_factory()
    settings = await OrganizationSettings.get(organization_id=organization.id)
    assert settings.segment_seconds == 300
    assert settings.auto_transcribe is True
    templates = await SummaryTemplate.filter(organization_id=organization.id).order_by('position')
    assert [(t.name, t.auto) for t in templates] == [
        ('Кратко', True),
        ('Решения и договорённости', False),
        ('Задачи и ответственные', False),
    ]


@pytest.mark.asyncio
async def test_organization_created_through_the_api_is_seeded(api_client, user_factory, auth_headers):
    user = await user_factory()
    response = await api_client.post(
        '/api/v1/organizations', headers=await auth_headers(user), json={'name': 'Команда', 'key': 'team'}
    )
    assert response.status_code == 201
    organization = await Organization.get(key='team')
    assert await SummaryTemplate.filter(organization=organization).count() == 3


@pytest.mark.asyncio
async def test_existing_organization_without_settings_is_seeded_lazily_once(organization_factory):
    organization = await organization_factory()
    await OrganizationSettings.filter(organization_id=organization.id).delete()
    await SummaryTemplate.filter(organization_id=organization.id, auto=False).delete()
    await OrganizationSettingsService.ensure(organization)
    await OrganizationSettingsService.ensure(organization)
    # Templates exist, so nothing is re-seeded on top of them.
    assert await SummaryTemplate.filter(organization_id=organization.id).count() == 1
    assert await OrganizationSettings.filter(organization_id=organization.id).count() == 1


@pytest.mark.asyncio
async def test_only_admins_read_settings(api_client, auth_headers, team):
    organization, admin, member = team
    response = await api_client.get('/api/v1/ai-settings/current', headers=await auth_headers(member, organization))
    assert response.status_code == 403
    response = await api_client.get('/api/v1/ai-settings/current', headers=await auth_headers(admin, organization))
    assert response.status_code == 200
    assert response.json()['has_api_key'] is False
    assert response.json()['openrouter_base_url'] == 'https://openrouter.ai/api/v1'
    response = await api_client.get('/api/v1/ai-settings/current', headers=await auth_headers(admin))
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_admin_of_another_organization_is_not_admin_here(api_client, auth_headers, team, organization_factory):
    organization, _, member = team
    other = await organization_factory()
    await OrganizationUser.filter(organization=other, user=member).delete()
    await OrganizationUser.create(organization=other, user=member, role=OrganizationRole.OWNER)
    response = await api_client.get('/api/v1/ai-settings/current', headers=await auth_headers(member, organization))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_api_key_is_stored_encrypted_and_never_returned(api_client, auth_headers, team):
    organization, admin, _ = team
    headers = await auth_headers(admin, organization)
    response = await api_client.patch(
        '/api/v1/ai-settings/current', headers=headers, json={'openrouter_api_key': f'  {SECRET} '}
    )
    assert response.status_code == 200
    assert SECRET not in response.text
    assert response.json()['has_api_key'] is True
    assert response.json()['api_key_hint'] == 'cdef'
    stored = await OrganizationSettings.get(organization_id=organization.id)
    assert SECRET not in stored.openrouter_api_key_encrypted
    assert OrganizationSettingsService.api_key(stored) == SECRET

    # Untouched by other updates, removed by an empty value.
    await api_client.patch('/api/v1/ai-settings/current', headers=headers, json={'auto_tags': False})
    assert (
        OrganizationSettingsService.api_key(await OrganizationSettings.get(organization_id=organization.id)) == SECRET
    )
    response = await api_client.patch('/api/v1/ai-settings/current', headers=headers, json={'openrouter_api_key': ''})
    assert response.json()['has_api_key'] is False
    assert response.json()['api_key_hint'] is None


@pytest.mark.asyncio
async def test_models_and_defaults_validation(api_client, auth_headers, team):
    organization, admin, _ = team
    headers = await auth_headers(admin, organization)
    url = '/api/v1/ai-settings/current'
    response = await api_client.patch(
        url,
        headers=headers,
        json={
            'transcription_models': ['google/gemini-2.5-flash', 'openai/whisper-large', 'google/gemini-2.5-flash'],
            'transcription_default_model': 'openai/whisper-large',
            'summary_models': ['anthropic/claude-sonnet'],
            'segment_seconds': 600,
            'language': 'ru',
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['transcription_models'] == ['google/gemini-2.5-flash', 'openai/whisper-large']
    assert body['transcription_default_model'] == 'openai/whisper-large'
    # A default that was not given falls back to the first allowed model.
    assert body['summary_default_model'] == 'anthropic/claude-sonnet'
    assert body['segment_seconds'] == 600

    response = await api_client.patch(url, headers=headers, json={'transcription_default_model': 'other/model'})
    assert response.status_code == 400
    assert 'в списке разрешённых' in response.json()['error']['message']

    # Removing the default from the list moves it to the first remaining model.
    response = await api_client.patch(url, headers=headers, json={'transcription_models': ['google/gemini-2.5-flash']})
    assert response.json()['transcription_default_model'] == 'google/gemini-2.5-flash'

    for payload in ({'segment_seconds': 30}, {'segment_seconds': 901}, {'language': 'Russian'}, {'unknown': 1}):
        response = await api_client.patch(url, headers=headers, json=payload)
        assert response.status_code == 422, payload
    for base_url in ('ftp://router.test', 'https://user:pass@router.test', 'router.test'):
        response = await api_client.patch(url, headers=headers, json={'openrouter_base_url': base_url})
        assert response.status_code == 400, base_url
    response = await api_client.patch(url, headers=headers, json={'openrouter_base_url': 'http://llm.local:8080/v1/'})
    assert response.json()['openrouter_base_url'] == 'http://llm.local:8080/v1'


@pytest.mark.asyncio
async def test_members_read_options_without_secrets(api_client, auth_headers, team):
    organization, admin, member = team
    await api_client.patch(
        '/api/v1/ai-settings/current',
        headers=await auth_headers(admin, organization),
        json={'openrouter_api_key': SECRET, 'transcription_models': ['google/gemini-2.5-flash']},
    )
    response = await api_client.get('/api/v1/ai-settings/options', headers=await auth_headers(member, organization))
    assert response.status_code == 200
    assert response.json() == {
        'configured': True,
        'transcription_models': ['google/gemini-2.5-flash'],
        'transcription_default_model': 'google/gemini-2.5-flash',
        'summary_models': [],
        'summary_default_model': None,
    }
    assert SECRET not in response.text


@pytest.mark.asyncio
async def test_connection_test_reports_ok_and_errors(api_client, auth_headers, team, provider):
    organization, admin, member = team
    headers = await auth_headers(admin, organization)
    provider.add('/key', httpx2.Response(200, json={'data': {'label': 'x'}}))
    response = await api_client.post('/api/v1/ai-settings/test', headers=headers, json={})
    assert response.json() == {'ok': False, 'message': 'Укажите ключ API'}

    response = await api_client.post('/api/v1/ai-settings/test', headers=headers, json={'openrouter_api_key': SECRET})
    assert response.json() == {'ok': True, 'message': 'Ключ работает'}
    assert provider.calls('/key')[0].headers['authorization'] == f'Bearer {SECRET}'

    provider.routes['/key'] = [error_reply(401, 'User not found')]
    response = await api_client.post('/api/v1/ai-settings/test', headers=headers, json={'openrouter_api_key': SECRET})
    assert response.json() == {'ok': False, 'message': 'Ключ OpenRouter не принят: проверьте его в настройках AI'}

    response = await api_client.post(
        '/api/v1/ai-settings/test', headers=await auth_headers(member, organization), json={}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_model_catalog_is_filtered_searched_and_cached(api_client, auth_headers, team, provider):
    organization, admin, _ = team
    headers = await auth_headers(admin, organization)
    response = await api_client.get('/api/v1/ai-settings/models', headers=headers, params={'kind': 'audio'})
    assert response.status_code == 400
    assert response.json()['error']['message'].startswith('AI не настроен')

    await api_client.patch('/api/v1/ai-settings/current', headers=headers, json={'openrouter_api_key': SECRET})
    response = await api_client.get('/api/v1/ai-settings/models', headers=headers, params={'kind': 'audio'})
    assert response.status_code == 200
    assert [model['id'] for model in response.json()] == ['google/gemini-2.5-flash', 'openai/whisper-large']
    gemini = response.json()[0]
    assert gemini['max_completion_tokens'] == 65535
    assert gemini['prompt_price'] == '0.0000003'

    response = await api_client.get('/api/v1/ai-settings/models', headers=headers, params={'kind': 'text'})
    assert [model['id'] for model in response.json()] == ['anthropic/claude-sonnet', 'google/gemini-2.5-flash']
    response = await api_client.get(
        '/api/v1/ai-settings/models', headers=headers, params={'kind': 'text', 'search': 'CLAUDE'}
    )
    assert [model['id'] for model in response.json()] == ['anthropic/claude-sonnet']
    # One catalog fetch (two listings) served all three requests.
    assert len(provider.calls('/models')) == 2

    settings = await OrganizationSettings.get(organization_id=organization.id)
    assert (
        await ModelCatalogService.transcription_mode(settings, 'openai/whisper-large')
        == TranscriptionMode.TRANSCRIPTION
    )
    assert await ModelCatalogService.transcription_mode(settings, 'google/gemini-2.5-flash') == TranscriptionMode.CHAT


@pytest.mark.asyncio
async def test_summary_templates_members_read_admins_manage(api_client, auth_headers, team):
    organization, admin, member = team
    member_headers = await auth_headers(member, organization)
    admin_headers = await auth_headers(admin, organization)

    response = await api_client.get('/api/v1/summary-templates', headers=member_headers)
    assert response.status_code == 200
    assert response.json()['data'][0]['name'] == 'Кратко'

    body = {'name': 'Риски', 'prompt': 'Выпиши риски'}
    assert (await api_client.post('/api/v1/summary-templates', headers=member_headers, json=body)).status_code == 403
    response = await api_client.post('/api/v1/summary-templates', headers=admin_headers, json=body)
    assert response.status_code == 201
    created = response.json()
    assert created['position'] == 3
    assert created['created_by_id'] == str(admin.id)

    template_id = created['id']
    response = await api_client.patch(
        f'/api/v1/summary-templates/{template_id}', headers=member_headers, json={'auto': True}
    )
    assert response.status_code == 403
    response = await api_client.patch(
        f'/api/v1/summary-templates/{template_id}', headers=admin_headers, json={'auto': True, 'name': None}
    )
    assert response.status_code == 200
    assert response.json()['auto'] is True
    assert response.json()['name'] == 'Риски'

    response = await api_client.get('/api/v1/summary-templates', headers=member_headers, params={'auto': True})
    assert {item['name'] for item in response.json()['data']} == {'Кратко', 'Риски'}

    assert (
        await api_client.delete(f'/api/v1/summary-templates/{template_id}', headers=member_headers)
    ).status_code == 403
    assert (
        await api_client.delete(f'/api/v1/summary-templates/{template_id}', headers=admin_headers)
    ).status_code == 204


@pytest.mark.asyncio
async def test_summary_templates_are_isolated_between_organizations(
    api_client, auth_headers, team, organization_factory
):
    organization, admin, _ = team
    other = await organization_factory()
    foreign = await SummaryTemplate.filter(organization_id=other.id).first()
    assert foreign is not None
    headers = await auth_headers(admin, organization)
    response = await api_client.get(f'/api/v1/summary-templates/{foreign.id}', headers=headers)
    assert response.status_code == 404
    response = await api_client.delete(f'/api/v1/summary-templates/{foreign.id}', headers=headers)
    assert response.status_code == 404
