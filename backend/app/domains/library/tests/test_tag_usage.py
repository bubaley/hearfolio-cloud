import pytest

from app.domains.library.models import RecordingVisibility, Tag


@pytest.mark.asyncio
async def test_tag_usage_counts_only_recordings_the_caller_sees(api_client, library):
    sales = await Tag.create(organization=library.org, name='Sales', name_key='sales')
    hiring = await Tag.create(organization=library.org, name='Hiring', name_key='hiring')
    await Tag.create(organization=library.org, name='Unused', name_key='unused')
    private_project = await library.project(private=True, members=(library.author,))

    shared = await library.recording()
    await shared.tags.add(sales, hiring)
    personal = await library.recording(visibility=RecordingVisibility.PERSONAL)
    await personal.tags.add(sales)
    in_private_project = await library.recording(project=private_project)
    await in_private_project.tags.add(sales)
    deleted = await library.recording(deleted=True)
    await deleted.tags.add(sales)

    async def usage(user) -> dict[str, int]:
        response = await api_client.get('/api/v1/tags/usage', headers=library.h(user))
        assert response.status_code == 200, response.text
        return {row['tag_id']: row['recordings_count'] for row in response.json()}

    assert await usage(library.author) == {str(sales.id): 3, str(hiring.id): 1}
    # A member sees neither the author's personal recording nor the private project; deleted ones never count.
    assert await usage(library.member) == {str(sales.id): 1, str(hiring.id): 1}
    assert await usage(library.outsider) == {}
