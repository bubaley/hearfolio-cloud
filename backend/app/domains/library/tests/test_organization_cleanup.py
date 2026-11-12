import pytest

from app.domains.library.models import ProjectMember, Recording
from app.domains.library.services.storage_cleanup import StorageCleanup
from app.domains.organization.models import OrganizationRole, OrganizationUser


@pytest.mark.asyncio
async def test_deleting_an_organization_deletes_its_audio(api_client, auth_headers, s3, library, monkeypatch):
    uploaded = await library.recording()
    uploading = await library.recording()
    await Recording.filter(id=uploading.id).update(upload_id='open-upload')
    foreign = await library.recording(author=library.outsider, organization=library.other_org)
    await OrganizationUser.filter(organization=library.org, user=library.author).update(role=OrganizationRole.OWNER)

    batches: list[tuple[list[str], list[list[str]]]] = []

    async def kick(keys, uploads):
        batches.append((keys, uploads))
        return True

    monkeypatch.setattr(StorageCleanup, '_kick', staticmethod(kick))
    response = await api_client.delete(
        f'/api/v1/organizations/{library.org.id}', headers=await auth_headers(library.author, library.org)
    )
    assert response.status_code == 204, response.text
    assert not await Recording.filter(organization_id=library.org.id).exists()

    assert len(batches) == 1
    keys, uploads = batches[0]
    assert sorted(keys) == sorted([uploaded.audio_key, uploading.audio_key])
    assert uploads == [[uploading.audio_key, 'open-upload']]
    assert foreign.audio_key not in keys

    # The task body: abort open uploads, then one batch delete.
    s3.delete_objects = lambda **kwargs: {'Deleted': kwargs['Delete']['Objects']}
    assert await StorageCleanup.delete(keys, uploads) == []
    s3.abort_multipart_upload.assert_called_once_with(Bucket='media', Key=uploading.audio_key, UploadId='open-upload')


@pytest.mark.asyncio
async def test_batch_delete_reports_failures(s3):
    s3.delete_objects = lambda **kwargs: {'Errors': [{'Key': 'b', 'Code': 'AccessDenied'}]}
    assert await StorageCleanup.delete(['a', 'b'], []) == ['b']


@pytest.mark.asyncio
async def test_leaving_the_organization_drops_private_project_memberships(api_client, s3, library):
    project = await library.project(private=True, members=(library.member, library.author))
    membership = await OrganizationUser.get(organization=library.org, user=library.member)
    response = await api_client.delete(f'/api/v1/organization-users/{membership.id}', headers=library.h(library.member))
    assert response.status_code == 204, response.text
    assert not await ProjectMember.filter(project_id=project.id, user_id=library.member.id).exists()
    assert await ProjectMember.filter(project_id=project.id, user_id=library.author.id).exists()
