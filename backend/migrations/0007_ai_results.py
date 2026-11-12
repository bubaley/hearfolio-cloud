from tortoise import migrations
from tortoise.migrations import operations as ops
import functools
from app.domains.ai.models import ResultStatus
from json import dumps, loads
from tortoise.fields.base import OnDelete
from uuid import uuid4
from tortoise import fields

class Migration(migrations.Migration):
    dependencies = [('models', '0006_library')]

    initial = False

    operations = [
        ops.CreateModel(
            name='RecordingProcessing',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('recording', fields.OneToOneField('models.Recording', source_field='recording_id', db_constraint=True, to_field='id', related_name='processing', on_delete=OnDelete.CASCADE)),
                ('titled', fields.BooleanField(default=False)),
                ('classified', fields.BooleanField(default=False)),
                ('summarized', fields.BooleanField(default=False)),
                ('retranscribe_model', fields.CharField(null=True, max_length=255)),
                ('retranscribe_segments', fields.JSONField(default=list, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
            ],
            options={'table': 'recording_processing', 'app': 'models', 'pk_attr': 'id', 'table_description': 'Pipeline bookkeeping per recording, so a re-delivered or retried task never repeats finished steps, and a'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='RecordingResult',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('recording', fields.ForeignKeyField('models.Recording', source_field='recording_id', db_constraint=True, to_field='id', related_name='results', on_delete=OnDelete.CASCADE)),
                ('template', fields.ForeignKeyField('models.SummaryTemplate', source_field='template_id', null=True, db_constraint=True, to_field='id', related_name='results', on_delete=OnDelete.SET_NULL)),
                ('title', fields.CharField(max_length=255)),
                ('prompt', fields.TextField(unique=False)),
                ('model', fields.CharField(max_length=255)),
                ('status', fields.CharEnumField(default=ResultStatus.QUEUED, description='QUEUED: queued\nRUNNING: running\nDONE: done\nFAILED: failed', enum_type=ResultStatus, max_length=16)),
                ('content', fields.TextField(default='', unique=False)),
                ('error_message', fields.CharField(null=True, max_length=2000)),
                ('created_by', fields.ForeignKeyField('models.User', source_field='created_by_id', null=True, db_constraint=True, to_field='id', related_name='recording_results', on_delete=OnDelete.SET_NULL)),
            ],
            options={'table': 'recording_result', 'app': 'models', 'pk_attr': 'id', 'table_description': 'A summary of a recording made by a text model from a template or a custom prompt.'},
            bases=['BaseModel'],
        ),
    ]
