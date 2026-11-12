from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise import fields

class Migration(migrations.Migration):
    dependencies = [('models', '0007_ai_results')]

    initial = False

    operations = [
        ops.AddField(
            model_name='RecordingResult',
            name='error_code',
            field=fields.CharField(null=True, max_length=64),
        ),
    ]
