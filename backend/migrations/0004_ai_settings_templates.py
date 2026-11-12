from tortoise import migrations
from tortoise.migrations import operations as ops
import functools
from json import dumps, loads
from tortoise.fields.base import OnDelete
from uuid import uuid4
from tortoise import fields

class Migration(migrations.Migration):
    dependencies = [('models', '0003_auto_20261113_0036')]

    initial = False

    operations = [
        ops.CreateModel(
            name='OrganizationSettings',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('organization', fields.OneToOneField('models.Organization', source_field='organization_id', db_constraint=True, to_field='id', related_name='ai_settings', on_delete=OnDelete.CASCADE)),
                ('openrouter_base_url', fields.CharField(default='https://openrouter.ai/api/v1', max_length=512)),
                ('openrouter_api_key_encrypted', fields.TextField(default='', unique=False)),
                ('openrouter_api_key_hint', fields.CharField(default='', max_length=8)),
                ('transcription_models', fields.JSONField(default=list, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
                ('transcription_default_model', fields.CharField(null=True, max_length=255)),
                ('summary_models', fields.JSONField(default=list, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
                ('summary_default_model', fields.CharField(null=True, max_length=255)),
                ('auto_transcribe', fields.BooleanField(default=True)),
                ('auto_title', fields.BooleanField(default=True)),
                ('auto_tags', fields.BooleanField(default=True)),
                ('auto_project', fields.BooleanField(default=True)),
                ('segment_seconds', fields.IntField(default=300)),
                ('language', fields.CharField(default='auto', max_length=16)),
            ],
            options={'table': 'organization_settings', 'app': 'models', 'pk_attr': 'id', 'table_description': 'AI configuration of one organization; created lazily with defaults (`OrganizationSettingsService.ensure`).'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='SummaryTemplate',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('organization', fields.ForeignKeyField('models.Organization', source_field='organization_id', db_constraint=True, to_field='id', related_name='summary_templates', on_delete=OnDelete.CASCADE)),
                ('name', fields.CharField(max_length=128)),
                ('prompt', fields.TextField(unique=False)),
                ('auto', fields.BooleanField(default=False)),
                ('position', fields.IntField(default=0)),
                ('created_by', fields.ForeignKeyField('models.User', source_field='created_by_id', null=True, db_constraint=True, to_field='id', related_name='summary_templates', on_delete=OnDelete.SET_NULL)),
            ],
            options={'table': 'summary_template', 'app': 'models', 'pk_attr': 'id'},
            bases=['BaseModel'],
        ),
    ]
