from tortoise import migrations
from tortoise.migrations import operations as ops
import functools
from app.domains.organization.models import OrganizationRole
from app.domains.sso.models import SsoJoinPolicy, SsoLoginIntent, SsoLoginMode
from json import dumps, loads
from tortoise.fields.base import OnDelete
from uuid import uuid4
from tortoise import fields

class Migration(migrations.Migration):
    dependencies = [('models', '0011_summary_template_description')]

    initial = False

    operations = [
        ops.CreateModel(
            name='SsoProvider',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('organization', fields.OneToOneField('models.Organization', source_field='organization_id', db_constraint=True, to_field='id', related_name='sso_provider', on_delete=OnDelete.CASCADE)),
                ('issuer', fields.CharField(max_length=512)),
                ('client_id', fields.CharField(max_length=255)),
                ('client_secret_encrypted', fields.TextField(unique=False)),
                ('scopes', fields.JSONField(default=list, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
                ('button_label', fields.CharField(default='', max_length=64)),
                ('metadata', fields.JSONField(default=dict, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
                ('metadata_fetched_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ('login_mode', fields.CharEnumField(default=SsoLoginMode.PASSWORD_AND_SSO, description='PASSWORD_AND_SSO: password_and_sso\nSSO_ONLY: sso_only', enum_type=SsoLoginMode, max_length=24)),
                ('join_policy', fields.CharEnumField(default=SsoJoinPolicy.INVITE_ONLY, description='INVITE_ONLY: invite_only\nPROVIDER: provider', enum_type=SsoJoinPolicy, max_length=24)),
                ('allowed_email_domains', fields.JSONField(default=list, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
                ('required_groups', fields.JSONField(default=list, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
                ('default_role', fields.CharEnumField(default=OrganizationRole.MEMBER, description='OWNER: owner\nADMIN: admin\nMEMBER: member', enum_type=OrganizationRole, max_length=16)),
                ('owner_password_fallback', fields.BooleanField(default=True)),
                ('revalidate_interval_minutes', fields.IntField(default=10)),
            ],
            options={'table': 'sso_provider', 'app': 'models', 'pk_attr': 'id', 'table_description': "The OpenID Connect provider an organization signs in with, plus the organization's sign-in rules. Hearfolio is"},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='SsoIdentity',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('provider', fields.ForeignKeyField('models.SsoProvider', source_field='provider_id', db_constraint=True, to_field='id', related_name='identities', on_delete=OnDelete.CASCADE)),
                ('user', fields.ForeignKeyField('models.User', source_field='user_id', db_constraint=True, to_field='id', related_name='sso_identities', on_delete=OnDelete.CASCADE)),
                ('subject', fields.CharField(max_length=255)),
                ('email', fields.CharField(default='', max_length=255)),
                ('email_verified', fields.BooleanField(default=False)),
                ('name', fields.CharField(default='', max_length=255)),
                ('groups', fields.JSONField(default=list, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
                ('created_user', fields.BooleanField(default=False)),
                ('last_login_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
            ],
            options={'table': 'sso_identity', 'app': 'models', 'unique_together': (('provider', 'subject'), ('provider', 'user')), 'pk_attr': 'id', 'table_description': 'A provider account (`sub`, stable per provider) linked to a Hearfolio user. Never matched by email alone.'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='SsoLoginRequest',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('provider', fields.ForeignKeyField('models.SsoProvider', source_field='provider_id', db_constraint=True, to_field='id', related_name='login_requests', on_delete=OnDelete.CASCADE)),
                ('state_hash', fields.CharField(unique=True, max_length=64)),
                ('browser_hash', fields.CharField(max_length=64)),
                ('nonce', fields.CharField(max_length=128)),
                ('code_verifier_encrypted', fields.TextField(unique=False)),
                ('intent', fields.CharEnumField(default=SsoLoginIntent.LOGIN, description='LOGIN: login\nLINK: link', enum_type=SsoLoginIntent, max_length=8)),
                ('user', fields.ForeignKeyField('models.User', source_field='user_id', null=True, db_constraint=True, to_field='id', related_name='sso_login_requests', on_delete=OnDelete.CASCADE)),
                ('redirect_path', fields.CharField(default='', max_length=1024)),
                ('expires_at', fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ('used_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
            ],
            options={'table': 'sso_login_request', 'app': 'models', 'pk_attr': 'id', 'table_description': 'A pending authorization request: `state` (stored as SHA-256), `nonce`, the PKCE verifier and the browser it'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='SsoSession',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('provider', fields.ForeignKeyField('models.SsoProvider', source_field='provider_id', db_constraint=True, to_field='id', related_name='sessions', on_delete=OnDelete.CASCADE)),
                ('identity', fields.ForeignKeyField('models.SsoIdentity', source_field='identity_id', db_constraint=True, to_field='id', related_name='sessions', on_delete=OnDelete.CASCADE)),
                ('user', fields.ForeignKeyField('models.User', source_field='user_id', db_constraint=True, to_field='id', related_name='sso_sessions', on_delete=OnDelete.CASCADE)),
                ('family_id', fields.UUIDField(unique=True)),
                ('refresh_token_encrypted', fields.TextField(default='', unique=False)),
                ('access_token_encrypted', fields.TextField(default='', unique=False)),
                ('access_token_expires_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ('validated_at', fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ('check_started_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ('revoked_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ('revoke_reason', fields.CharField(default='', max_length=32)),
            ],
            options={'table': 'sso_session', 'app': 'models', 'pk_attr': 'id', 'table_description': 'A Hearfolio session established through a provider: the web session family (`family_id` of RefreshSession)'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='SsoSessionToken',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('session', fields.ForeignKeyField('models.SsoSession', source_field='session_id', db_constraint=True, to_field='id', related_name='tokens', on_delete=OnDelete.CASCADE)),
                ('token', fields.OneToOneField('models.UserToken', source_field='token_id', db_constraint=True, to_field='id', related_name='sso_session_link', on_delete=OnDelete.CASCADE)),
            ],
            options={'table': 'sso_session_token', 'app': 'models', 'pk_attr': 'id', 'table_description': 'An app API token approved (OAuth consent) from an SSO session: it lives and dies with that session.'},
            bases=['BaseModel'],
        ),
        ops.AddField(
            model_name='OAuthAuthorizationCode',
            name='session_family_id',
            field=fields.UUIDField(null=True),
        ),
    ]
