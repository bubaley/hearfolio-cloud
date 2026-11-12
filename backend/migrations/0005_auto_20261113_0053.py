from tortoise import migrations
from tortoise.migrations import operations as ops
from app.domains.organization.models import OrganizationRole
from tortoise.fields.base import OnDelete
from uuid import uuid4
from tortoise import fields

class Migration(migrations.Migration):
    dependencies = [('models', '0004_ai_settings_templates')]

    initial = False

    operations = [
        ops.CreateModel(
            name='OAuthAuthorizationCode',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('user', fields.ForeignKeyField('models.User', source_field='user_id', db_constraint=True, to_field='id', related_name='oauth_codes', on_delete=OnDelete.CASCADE)),
                ('code_hash', fields.CharField(unique=True, max_length=64)),
                ('client_id', fields.CharField(max_length=64)),
                ('redirect_uri', fields.CharField(max_length=255)),
                ('code_challenge', fields.CharField(max_length=64)),
                ('device_name', fields.CharField(max_length=64)),
                ('expires_at', fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ('used_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ('token', fields.ForeignKeyField('models.UserToken', source_field='token_id', null=True, db_constraint=True, to_field='id', related_name='oauth_codes', on_delete=OnDelete.SET_NULL)),
            ],
            options={'table': 'oauth_authorization_code', 'app': 'models', 'pk_attr': 'id', 'table_description': 'A single-use authorization code (OAuth 2.0 + PKCE) issued to a signed-in user for a native app. Only the'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='OrganizationInvite',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('organization', fields.ForeignKeyField('models.Organization', source_field='organization_id', db_constraint=True, to_field='id', related_name='invites', on_delete=OnDelete.CASCADE)),
                ('role', fields.CharEnumField(default=OrganizationRole.MEMBER, description='OWNER: owner\nADMIN: admin\nMEMBER: member', enum_type=OrganizationRole, max_length=16)),
                ('token_hash', fields.CharField(unique=True, max_length=64)),
                ('created_by', fields.ForeignKeyField('models.User', source_field='created_by_id', null=True, db_constraint=True, to_field='id', related_name='created_invites', on_delete=OnDelete.SET_NULL)),
                ('expires_at', fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ('accepted_by', fields.ForeignKeyField('models.User', source_field='accepted_by_id', null=True, db_constraint=True, to_field='id', related_name='accepted_invites', on_delete=OnDelete.SET_NULL)),
                ('accepted_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ('revoked_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
            ],
            options={'table': 'organization_invite', 'app': 'models', 'pk_attr': 'id', 'table_description': 'A single-use link that adds whoever accepts it to the organization with `role` (admin or member).'},
            bases=['BaseModel'],
        ),
    ]
