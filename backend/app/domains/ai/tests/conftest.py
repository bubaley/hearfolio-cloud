import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx2
import pytest

from app.core.services.crypto_service import CryptoService
from app.domains.ai.models import OrganizationSettings
from app.domains.ai.services.audio_segmenter import AudioSegmenter
from app.domains.ai.services.model_catalog_service import ModelCatalogService
from app.domains.ai.services.openrouter_client import OpenRouterClient
from app.domains.ai.services.recording_processor import RecordingProcessor
from app.domains.ai.tests.fakes import chat_reply
from app.domains.library.models import Project, Recording, RecordingStatus, UploadState
from app.domains.organization.models import Organization, OrganizationRole, OrganizationUser
from app.domains.user.models import User

AUDIO_MODEL = 'google/gemini-2.5-flash'
TEXT_MODEL = 'anthropic/claude-sonnet'


class FakeAI:
    """
    A scripted OpenRouter: answers transcription, title, classification and summary requests by their shape.
    `transcripts` is consumed one per audio request (an `httpx2.Response` entry is returned as is); `hooks` run on
    each audio request before answering (to simulate a user acting mid-processing).
    """

    def __init__(self) -> None:
        self.transcripts: list[str | httpx2.Response] = []
        self.default_transcript = 'Речь.'
        self.title = 'Планирование релиза'
        self.classification: dict[str, Any] = {'tags': ['релиз', 'Бэкенд'], 'project': None, 'project_confidence': 0}
        self.summary = '- главное'
        self.audio_requests: list[dict[str, Any]] = []
        self.text_requests: list[dict[str, Any]] = []
        self.hooks: list[Any] = []

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith('/models'):
            return httpx2.Response(200, json={'data': []})
        body = json.loads(request.content)
        content = body['messages'][-1]['content']
        if isinstance(content, list):
            self.audio_requests.append(body)
            for hook in self.hooks:
                await hook(len(self.audio_requests))
            reply = self.transcripts.pop(0) if self.transcripts else self.default_transcript
            return reply if isinstance(reply, httpx2.Response) else chat_reply(reply)
        self.text_requests.append(body)
        system = body['messages'][0]['content']
        if 'name voice recordings' in system:
            return chat_reply(self.title)
        if 'organize voice recordings' in system:
            return chat_reply(json.dumps(self.classification, ensure_ascii=False))
        return chat_reply(self.summary)


@pytest.fixture
def fake_ai(monkeypatch) -> FakeAI:
    fake = FakeAI()
    monkeypatch.setattr(OpenRouterClient, 'default_transport', httpx2.MockTransport(fake.handler))
    ModelCatalogService.clear_memory_cache()
    return fake


class FakeSegmenter(AudioSegmenter):
    """No ffmpeg: a fixed duration, placeholder chunks."""

    def __init__(self, duration_ms: int):
        super().__init__()
        self.duration_ms = duration_ms
        self.cuts: list[tuple[int, int]] = []

    async def probe_duration_ms(self, source: Path) -> int:
        return self.duration_ms

    async def cut(self, source: Path, start_ms: int, end_ms: int, target_dir: Path) -> Path:
        self.cuts.append((start_ms, end_ms))
        path = target_dir / f'{start_ms}-{end_ms}.mp3'
        path.write_bytes(b'mp3')
        return path

    async def is_silent(self, chunk: Path) -> bool:
        return False


@dataclass
class Team:
    org: Organization
    author: User
    member: User
    admin: User
    settings: OrganizationSettings
    downloads: list[str] = field(default_factory=list)

    async def recording(self, **kwargs: Any) -> Recording:
        values: dict[str, Any] = {
            'organization': self.org,
            'client_id': uuid4(),
            'created_by': self.author,
            'recorded_at': datetime(2026, 11, 1, 10, tzinfo=UTC),
            'audio_key': f'hearfolio/2026/11/01/{uuid4().hex}.m4a',
            'audio_size': 1000,
            'audio_mime': 'audio/mp4',
            'upload_state': UploadState.UPLOADED,
            'status': RecordingStatus.QUEUED,
        }
        values.update(kwargs)
        return await Recording.create(**values)

    async def project(self, name: str, *, private: bool = False) -> Project:
        return await Project.create(organization=self.org, name=name, is_private=private, created_by=self.author)

    def processor(self, segmenter: AudioSegmenter, source: Path | None = None) -> RecordingProcessor:
        async def download(recording: Recording, target: Path) -> None:
            self.downloads.append(recording.audio_key)
            target.write_bytes(source.read_bytes() if source else b'audio')

        return RecordingProcessor(segmenter=segmenter, download=download)


@pytest.fixture
async def ai_team(user_factory) -> Team:
    author, member, admin = [await user_factory() for _ in range(3)]
    org = await Organization.create(name='Acme', key=f'acme-{uuid4().hex[:8]}')
    await OrganizationUser.create(organization=org, user=author)
    await OrganizationUser.create(organization=org, user=member)
    await OrganizationUser.create(organization=org, user=admin, role=OrganizationRole.ADMIN)
    settings = await OrganizationSettings.get(organization_id=org.id)
    settings.openrouter_api_key_encrypted = CryptoService.encrypt('sk-test-key')
    settings.transcription_models = [AUDIO_MODEL, 'other/audio']
    settings.transcription_default_model = AUDIO_MODEL
    settings.summary_models = [TEXT_MODEL]
    settings.summary_default_model = TEXT_MODEL
    settings.segment_seconds = 60
    await settings.save()
    return Team(org=org, author=author, member=member, admin=admin, settings=settings)
