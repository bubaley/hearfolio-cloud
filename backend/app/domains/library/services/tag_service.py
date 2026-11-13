import hashlib
from uuid import UUID

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.domains.library.models import Recording, Tag, TagColor
from app.domains.library.services.realtime import LibraryRealtime
from app.domains.library.services.visibility import LibraryVisibility
from app.domains.organization.services.organization_service import OrganizationService
from app.domains.user.models import User

TAG_NAME_MAX_LENGTH = 64


class TagService:
    """Tags are shared by the organization: any member creates them, org admins rename, recolor, merge and delete."""

    @staticmethod
    async def usage(user: User, organization_id: UUID) -> dict[UUID, int]:
        """Recordings per tag among the ones the user can see (tags without any are absent)."""
        rows = await (
            LibraryVisibility.recordings(user, organization_id)
            .filter(tags__id__isnull=False)
            .values_list('id', 'tags__id')
        )
        counts: dict[UUID, set[UUID]] = {}
        for recording_id, tag_id in rows:
            counts.setdefault(tag_id, set()).add(recording_id)
        return {tag_id: len(recordings) for tag_id, recordings in counts.items()}

    @staticmethod
    def normalize_name(name: str) -> str:
        return ' '.join(name.split())[:TAG_NAME_MAX_LENGTH]

    @classmethod
    def name_key(cls, name: str) -> str:
        return cls.normalize_name(name).casefold()

    @staticmethod
    def default_color(name: str) -> TagColor:
        """Stable color for a tag created without one (AI tags)."""
        colors = list(TagColor)
        digest = hashlib.sha256(name.casefold().encode()).digest()
        return colors[digest[0] % len(colors)]

    @classmethod
    def prepare(cls, tag: Tag) -> None:
        tag.name = cls.normalize_name(tag.name)
        if not tag.name:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Tag name is empty')
        tag.name_key = tag.name.casefold()

    @classmethod
    async def _save_unique(cls, tag: Tag) -> Tag:
        cls.prepare(tag)
        try:
            await tag.save()
        except IntegrityError:
            raise AppException.from_attrs(ErrorCode.CONFLICT, 'A tag with this name already exists')
        return tag

    @classmethod
    async def create(cls, tag: Tag) -> Tag:
        if tag.color is None:
            tag.color = cls.default_color(tag.name)
        return await cls._save_unique(tag)

    @staticmethod
    async def validate_manage(tag: Tag, actor: User) -> None:
        if not await OrganizationService.is_admin(actor, tag.organization_id):
            raise AppException.from_attrs(ErrorCode.FORBIDDEN, 'Only organization admins can change tags')

    @classmethod
    async def update(cls, tag: Tag, actor: User) -> Tag:
        await cls.validate_manage(tag, actor)
        await cls._save_unique(tag)
        await LibraryRealtime.touch(Recording.filter(tags__id=tag.id))
        return tag

    @classmethod
    async def delete(cls, tag: Tag, actor: User) -> None:
        await cls.validate_manage(tag, actor)
        recording_ids = await Recording.filter(tags__id=tag.id).values_list('id', flat=True)
        await tag.delete()
        await LibraryRealtime.touch(Recording.filter(id__in=recording_ids))

    @classmethod
    async def merge(cls, source: Tag, target: Tag, actor: User) -> Tag:
        """Every recording tagged `source` gets `target`; `source` is deleted."""
        await cls.validate_manage(source, actor)
        if source.organization_id != target.organization_id:
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, 'Tag not found')
        if source.id == target.id:
            raise AppException.from_attrs(ErrorCode.VALIDATION_ERROR, 'Cannot merge a tag into itself')
        recording_ids = await Recording.filter(tags__id=source.id).values_list('id', flat=True)
        async with in_transaction():
            already_tagged = set(
                await Recording.filter(tags__id=target.id, id__in=recording_ids).values_list('id', flat=True)
            )
            to_add = [r for r in await Recording.filter(id__in=recording_ids) if r.id not in already_tagged]
            if to_add:
                await target.recordings.add(*to_add)
            await source.delete()
        await LibraryRealtime.touch(Recording.filter(id__in=recording_ids))
        return target

    @classmethod
    async def get_or_create_many(cls, organization_id: UUID, names: list[str], limit: int | None = None) -> list[Tag]:
        """
        Tags by name, case-insensitively, in the order of `names` without duplicates; missing ones are created.
        At most `limit` names are considered, so nothing is created beyond it.
        """
        tags: list[Tag] = []
        seen: set[str] = set()
        for raw in names:
            if limit is not None and len(tags) >= limit:
                break
            name = cls.normalize_name(raw)
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            tag = await Tag.get_or_none(organization_id=organization_id, name_key=key)
            if tag is None:
                try:
                    tag = await Tag.create(
                        organization_id=organization_id, name=name, name_key=key, color=cls.default_color(name)
                    )
                except IntegrityError:
                    # Created concurrently (two pipeline runs): use the winner.
                    tag = await Tag.get(organization_id=organization_id, name_key=key)
            tags.append(tag)
        return tags
