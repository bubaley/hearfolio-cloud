import secrets
from datetime import timedelta

from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from app.core.exceptions import AppException
from app.core.schemas import ErrorCode
from app.core.services.crypto_service import CryptoService
from app.core.services.rate_limiter import invite_rate_limiter
from app.core.utils.date_utils import utcnow
from app.domains.organization.models import InviteState, Organization, OrganizationInvite, OrganizationUser
from app.domains.organization.schemas import InviteAcceptSchema, InvitePreviewSchema, OrganizationInviteCreateSchema
from app.domains.organization.services.organization_service import OrganizationService
from app.domains.user.models import User

# Unused expired/revoked invites stay listed (with their state) this long, then are deleted
INVITE_RETENTION = timedelta(days=30)
EMAIL_EXISTS = 'Войдите, чтобы принять приглашение'
INVITE_NOT_FOUND = 'Invite not found'
STATE_ERRORS = {
    InviteState.EXPIRED: ('The invite has expired', 'invite_expired'),
    InviteState.USED: ('The invite has already been used', 'invite_used'),
    InviteState.REVOKED: ('The invite has been revoked', 'invite_revoked'),
}


def _conflict(message: str, reason: str) -> AppException:
    return AppException.from_attrs(ErrorCode.CONFLICT, message, details={'reason': reason})


class InviteService:
    """
    Single-use invite links. The raw token is shown once; lookups go through its SHA-256. Public endpoints
    count failures (unknown token, taken email) per client IP and answer 429 over the limit.
    """

    # ADMIN

    @staticmethod
    async def create(
        organization: Organization, actor: User, data: OrganizationInviteCreateSchema
    ) -> tuple[OrganizationInvite, str]:
        token = secrets.token_urlsafe(32)
        invite = await OrganizationInvite.create(
            organization=organization,
            role=data.role,
            token_hash=CryptoService.hash_value(token),
            created_by=actor,
            expires_at=utcnow() + timedelta(days=data.expires_in_days),
        )
        return invite, token

    @staticmethod
    async def purge_stale() -> int:
        """Periodic: unused invites that expired or were revoked over INVITE_RETENTION ago (used ones stay)."""
        cutoff = utcnow() - INVITE_RETENTION
        return (
            await OrganizationInvite.filter(accepted_at__isnull=True)
            .filter(Q(expires_at__lt=cutoff) | Q(revoked_at__lt=cutoff))
            .delete()
        )

    @staticmethod
    async def revoke(invite: OrganizationInvite) -> OrganizationInvite:
        """Revoking twice is a no-op; a used invite cannot be revoked (remove the member instead)."""
        if invite.state == InviteState.USED:
            raise _conflict(*STATE_ERRORS[InviteState.USED])
        if invite.revoked_at is None:
            invite.revoked_at = utcnow()
            await invite.save(update_fields=['revoked_at', 'updated_at'])
        return invite

    # PUBLIC

    @staticmethod
    async def get_by_token(token: str, client_ip: str) -> OrganizationInvite:
        await InviteService._check_rate_limit(client_ip)
        invite = (
            await OrganizationInvite.filter(token_hash=CryptoService.hash_value(token))
            .select_related('organization', 'created_by')
            .first()
        )
        if invite is None:
            await invite_rate_limiter.hit(client_ip)
            raise AppException.from_attrs(ErrorCode.NOT_FOUND, INVITE_NOT_FOUND, details={'reason': 'invite_not_found'})
        return invite

    @staticmethod
    def preview(invite: OrganizationInvite) -> InvitePreviewSchema:
        inviter = invite.created_by
        inviter_name = f'{inviter.first_name} {inviter.last_name}'.strip() if inviter else None
        return InvitePreviewSchema(
            organization_name=invite.organization.name,
            role=invite.role,
            inviter_name=inviter_name or None,
            state=invite.state,
            expires_at=invite.expires_at,
        )

    @staticmethod
    async def accept(invite: OrganizationInvite, user: User) -> OrganizationUser:
        """A signed-in user joins. Already a member → 409 and the invite stays usable for someone else."""
        InviteService._validate_usable(invite)
        if await OrganizationUser.exists(organization_id=invite.organization_id, user_id=user.id):
            raise _conflict('You are already a member of this organization', 'already_member')
        async with in_transaction():
            await InviteService._claim(invite, user)
            return await OrganizationService.add_invited_member(invite.organization, user, invite.role)

    @staticmethod
    async def accept_with_registration(
        invite: OrganizationInvite, data: InviteAcceptSchema, client_ip: str
    ) -> tuple[User, OrganizationUser]:
        """Anonymous accept: create the account and join. An existing email must sign in first (409)."""
        InviteService._validate_usable(invite)
        if await User.exists(email__iexact=data.email):
            await invite_rate_limiter.hit(client_ip)
            raise _conflict(EMAIL_EXISTS, 'email_exists')
        first_name, _, last_name = data.name.strip().partition(' ')
        user = User(email=data.email, first_name=first_name, last_name=last_name.strip())
        await user.set_password_async(data.password)
        try:
            async with in_transaction():
                await user.save()
                await InviteService._claim(invite, user)
                membership = await OrganizationService.add_invited_member(invite.organization, user, invite.role)
        except IntegrityError:
            # A parallel registration took the email between the check and the insert.
            raise _conflict(EMAIL_EXISTS, 'email_exists')
        return user, membership

    # HELPERS

    @staticmethod
    async def _check_rate_limit(client_ip: str) -> None:
        if retry_after := await invite_rate_limiter.retry_after(client_ip):
            raise AppException.from_attrs(
                ErrorCode.RATE_LIMITED, 'Too many attempts', headers={'Retry-After': str(retry_after)}
            )

    @staticmethod
    def _validate_usable(invite: OrganizationInvite) -> None:
        if (state := invite.state) != InviteState.VALID:
            raise _conflict(*STATE_ERRORS[state])

    @staticmethod
    async def _claim(invite: OrganizationInvite, user: User) -> None:
        """Mark the invite used, atomically: of two parallel accepts only one gets it."""
        now = utcnow()
        claimed = await OrganizationInvite.filter(
            id=invite.id, accepted_at=None, revoked_at=None, expires_at__gt=now
        ).update(accepted_at=now, accepted_by_id=user.id, updated_at=now)
        if not claimed:
            await invite.refresh_from_db()
            InviteService._validate_usable(invite)
            raise _conflict(*STATE_ERRORS[InviteState.USED])
        invite.accepted_at = now
        invite.accepted_by_id = user.id
