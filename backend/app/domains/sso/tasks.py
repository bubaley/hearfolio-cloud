from app.core.broker import broker
from app.domains.sso.services.login_service import SsoLoginService


@broker.task(task_name='sso.purge_stale_login_requests', schedule=[{'cron': '53 3 * * *'}])
async def purge_stale_login_requests() -> int:
    """Daily: delete sign-in requests (state, nonce, PKCE verifier) that expired more than a day ago."""
    return await SsoLoginService.purge_stale_requests()
