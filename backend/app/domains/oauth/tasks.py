from app.core.broker import broker
from app.domains.oauth.services.oauth_service import OAuthService


@broker.task(task_name='oauth.purge_expired_codes', schedule=[{'cron': '29 3 * * *'}])
async def purge_expired_codes() -> int:
    """Daily: delete authorization codes that expired more than a day ago."""
    return await OAuthService.purge_expired_codes()
