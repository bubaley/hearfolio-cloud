from tortoise import migrations
from tortoise.migrations import operations as ops
from app.domains.ai.models import AIUsageKind
from tortoise.fields.base import OnDelete
from uuid import uuid4
from tortoise import fields

# Period reports per organization and the per-recording breakdown. Portable SQL (SQLite too).
INDEXES = {
    'ai_usage_org_created_at': 'ai_usage (organization_id, created_at)',
    'ai_usage_recording_id': 'ai_usage (recording_id)',
}


class Migration(migrations.Migration):
    dependencies = [('models', '0013_speaker_names')]

    initial = False

    operations = [
        ops.CreateModel(
            name='AIUsage',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('organization', fields.ForeignKeyField('models.Organization', source_field='organization_id', db_constraint=True, to_field='id', related_name='ai_usage', on_delete=OnDelete.CASCADE)),
                ('recording', fields.ForeignKeyField('models.Recording', source_field='recording_id', null=True, db_constraint=True, to_field='id', related_name='ai_usage', on_delete=OnDelete.SET_NULL)),
                ('result', fields.ForeignKeyField('models.RecordingResult', source_field='result_id', null=True, db_constraint=True, to_field='id', related_name='ai_usage', on_delete=OnDelete.SET_NULL)),
                ('user', fields.ForeignKeyField('models.User', source_field='user_id', null=True, db_constraint=True, to_field='id', related_name='ai_usage', on_delete=OnDelete.SET_NULL)),
                ('kind', fields.CharEnumField(description='TRANSCRIPTION: transcription\nTITLE: title\nTAGS: tags\nSPEAKERS: speakers\nSUMMARY: summary', enum_type=AIUsageKind, max_length=16)),
                ('model', fields.CharField(max_length=255)),
                ('input_tokens', fields.BigIntField(null=True)),
                ('output_tokens', fields.BigIntField(null=True)),
                ('reasoning_tokens', fields.BigIntField(null=True)),
                ('cached_tokens', fields.BigIntField(null=True)),
                ('audio_ms', fields.BigIntField(null=True)),
                ('cost_usd', fields.DecimalField(null=True, max_digits=20, decimal_places=10)),
            ],
            options={'table': 'ai_usage', 'app': 'models', 'pk_attr': 'id', 'table_description': 'One request to the AI provider and what it measured: tokens, audio seconds and the cost the provider charged'},
            bases=['BaseModel'],
        ),
        ops.RunSQL(
            [f'CREATE INDEX IF NOT EXISTS {name} ON {target}' for name, target in INDEXES.items()],
            reverse_sql=[f'DROP INDEX IF EXISTS {name}' for name in INDEXES],
        ),
    ]
