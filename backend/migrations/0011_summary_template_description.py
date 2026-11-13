from tortoise import fields, migrations
from tortoise.migrations import operations as ops

# Descriptions for the seeded default templates (a frozen copy of DEFAULT_SUMMARY_TEMPLATES at this point), filled
# in only where the description is still empty. Portable SQL (SQLite too).
DEFAULT_DESCRIPTIONS = {
    'Кратко': 'О чём запись и главные мысли в нескольких пунктах',
    'Решения и договорённости': 'Что решили, кто отвечает и какие вопросы остались открытыми',
    'Задачи и ответственные': 'Чек-лист задач со сроками, сгруппированный по ответственным',
}


class Migration(migrations.Migration):
    dependencies = [('models', '0010_library_indexes')]

    initial = False

    operations = [
        ops.AddField(
            model_name='SummaryTemplate',
            name='description',
            field=fields.CharField(default='', db_default='', max_length=200),
        ),
        ops.RunSQL(
            [
                f"UPDATE summary_template SET description = '{description}' WHERE name = '{name}' AND description = ''"
                for name, description in DEFAULT_DESCRIPTIONS.items()
            ],
            reverse_sql=[],
        ),
    ]
