from typing import Any
from uuid import UUID

from app.core.broker import broker
from app.domains.organization.services.invite_service import InviteService
from app.domains.organization.services.organization_websocket_service import OrganizationWebSocketService


@broker.task(task_name='organization.notify_members')
async def notify_organization_members(organization_id: UUID, message_type: str, data: dict[str, Any]) -> None:
    """Push a websocket event to the organization's members; runs in the taskiq worker, delivered via pub/sub."""
    await OrganizationWebSocketService.notify(organization_id, message_type, data)


@broker.task(task_name='organization.purge_stale_invites', schedule=[{'cron': '41 3 * * *'}])
async def purge_stale_invites() -> int:
    """Daily: delete unused invites that expired or were revoked more than 30 days ago."""
    return await InviteService.purge_stale()
