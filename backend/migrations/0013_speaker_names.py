from tortoise import migrations
from tortoise.migrations import operations as ops
import functools
from json import dumps, loads
from tortoise import fields

class Migration(migrations.Migration):
    dependencies = [('models', '0012_organization_sso')]

    initial = False

    operations = [
        ops.AddField(
            model_name='OrganizationSettings',
            name='auto_speaker_names',
            field=fields.BooleanField(default=True, db_default=True),
        ),
        ops.AddField(
            model_name='Recording',
            name='speaker_names',
            field=fields.JSONField(default=dict, db_default='{}', encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads),
        ),
        ops.AddField(
            model_name='RecordingProcessing',
            name='speakers_named',
            field=fields.BooleanField(default=False, db_default=False),
        ),
    ]
