from uuid import UUID

from app.domains.ai.models import SummaryTemplate
from app.domains.user.models import User


class SummaryTemplateService:
    @staticmethod
    async def create(template: SummaryTemplate, actor: User, *, append: bool) -> SummaryTemplate:
        """Save a new template by `actor`; `append` puts it after the existing ones."""
        template.created_by_id = actor.id
        if append:
            last = (
                await SummaryTemplate.filter(organization_id=template.organization_id)
                .order_by('-position')
                .first()
                .values_list('position', flat=True)
            )
            template.position = last + 1 if isinstance(last, int) else 0
        await template.save()
        return template

    @staticmethod
    async def auto_templates(organization_id: UUID) -> list[SummaryTemplate]:
        """Templates the pipeline runs after transcription, in display order."""
        return await SummaryTemplate.filter(organization_id=organization_id, auto=True).order_by(
            'position', 'created_at'
        )
