from uuid import UUID

from tortoise import fields

from app.core.models import BaseModel
from app.core.scope import Scope


class OAuthAuthorizationCode(BaseModel):
    """
    A single-use authorization code (OAuth 2.0 + PKCE) issued to a signed-in user for a native app. Only the
    SHA-256 of the code is stored. Exchanging it creates `token`; presenting a used code again deletes that token.
    """

    user = fields.ForeignKeyField('models.User', related_name='oauth_codes', on_delete=fields.CASCADE)
    user_id: UUID
    code_hash = fields.CharField(max_length=64, unique=True)
    client_id = fields.CharField(max_length=64)
    redirect_uri = fields.CharField(max_length=255)
    code_challenge = fields.CharField(max_length=64)
    device_name = fields.CharField(max_length=64)
    expires_at = fields.DatetimeField()
    used_at = fields.DatetimeField(null=True)
    token = fields.ForeignKeyField('models.UserToken', related_name='oauth_codes', null=True, on_delete=fields.SET_NULL)
    token_id: UUID | None

    tenant_scope = Scope(user='user_id')

    class Meta:
        table = 'oauth_authorization_code'
        ordering = ('created_at',)
