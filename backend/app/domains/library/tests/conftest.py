from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import boto3
import pytest

from app.core.services import s3_service as s3_module
from app.core.services.s3_service import S3Service
from app.domains.library.models import Project, ProjectMember, Recording, RecordingVisibility, UploadState
from app.domains.organization.models import Organization, OrganizationRole, OrganizationUser
from app.domains.user.models import User


class FakeS3Client:
    """Presigning through an offline botocore client; object operations are MagicMocks the test configures."""

    def __init__(self) -> None:
        self._presigner = boto3.client(
            's3', region_name='eu-central-1', aws_access_key_id='test-key', aws_secret_access_key='test-secret'
        )
        self.objects: dict[str, int] = {}
        self.head_object = MagicMock(side_effect=self._head)
        self.create_multipart_upload = MagicMock(return_value={'UploadId': 'upload-1'})
        self.list_parts = MagicMock(return_value={'Parts': [], 'IsTruncated': False})
        self.complete_multipart_upload = MagicMock(return_value={})
        self.abort_multipart_upload = MagicMock(return_value={})
        self.delete_object = MagicMock(return_value={})

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
        return self._presigner.generate_presigned_url(*args, **kwargs)

    def _head(self, Bucket: str, Key: str) -> dict[str, Any]:
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({'Error': {'Code': '404', 'Message': 'Not Found'}}, 'HeadObject')
        return {'ContentLength': self.objects[Key], 'ContentType': 'audio/mp4'}


@pytest.fixture
def s3(monkeypatch) -> FakeS3Client:
    client = FakeS3Client()
    monkeypatch.setattr(s3_module, '_s3_service_instance', S3Service(bucket='media', client=client))
    return client


@dataclass
class Library:
    """One organization with an author, a member, an admin; an outsider in another organization."""

    org: Organization
    other_org: Organization
    author: User
    member: User
    admin: User
    outsider: User
    headers: dict[str, dict[str, str]] = field(default_factory=dict)

    def h(self, user: User) -> dict[str, str]:
        return self.headers[str(user.id)]

    async def project(self, *, private: bool = False, members: tuple[User, ...] = (), name: str = 'Project') -> Project:
        project = await Project.create(organization=self.org, name=name, is_private=private, created_by=self.author)
        for user in members:
            await ProjectMember.create(project=project, user=user)
        return project

    async def recording(
        self,
        *,
        author: User | None = None,
        project: Project | None = None,
        visibility: RecordingVisibility = RecordingVisibility.ORGANIZATION,
        title: str = 'Recording',
        transcript: str = '',
        organization: Organization | None = None,
        deleted: bool = False,
    ) -> Recording:
        return await Recording.create(
            organization=organization or self.org,
            client_id=uuid4(),
            created_by=author or self.author,
            project=project,
            visibility=visibility,
            title=title,
            transcript_text=transcript,
            recorded_at=datetime(2026, 11, 1, 10, tzinfo=UTC),
            audio_key=f'hearfolio/2026/11/01/{uuid4().hex}.m4a',
            audio_size=1000,
            audio_mime='audio/mp4',
            upload_state=UploadState.UPLOADED,
            deleted_at=datetime(2026, 11, 2, tzinfo=UTC) if deleted else None,
        )


@pytest.fixture
async def library(user_factory, auth_headers) -> Library:
    author, member, admin, outsider = [await user_factory() for _ in range(4)]
    org = await Organization.create(name='Acme', key=f'acme-{uuid4().hex[:8]}')
    other_org = await Organization.create(name='Other', key=f'other-{uuid4().hex[:8]}')
    await OrganizationUser.create(organization=org, user=author)
    await OrganizationUser.create(organization=org, user=member)
    await OrganizationUser.create(organization=org, user=admin, role=OrganizationRole.ADMIN)
    await OrganizationUser.create(organization=other_org, user=outsider)
    library = Library(org=org, other_org=other_org, author=author, member=member, admin=admin, outsider=outsider)
    for user in (author, member, admin):
        library.headers[str(user.id)] = await auth_headers(user, org)
    library.headers[str(outsider.id)] = await auth_headers(outsider, other_org)
    return library
