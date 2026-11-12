from tortoise import migrations
from tortoise.migrations import operations as ops

# Organizations created before roles existed may have no owner: the earliest member becomes one, so the
# "at least one owner" rule holds and someone can delete the organization or grant ownership. Portable SQL.
PROMOTE_EARLIEST_MEMBER = """
UPDATE organization_user SET role = 'owner'
WHERE id IN (
    SELECT (
        SELECT first.id FROM organization_user first
        WHERE first.organization_id = o.id
        ORDER BY first.created_at, first.id
        LIMIT 1
    )
    FROM organization o
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_user owner_row
        WHERE owner_row.organization_id = o.id AND owner_row.role = 'owner'
    )
)
"""


class Migration(migrations.Migration):
    dependencies = [('models', '0008_result_error_code')]

    initial = False

    operations = [
        # Irreversible in meaning (we cannot know who was promoted); rolling back leaves the owners in place.
        ops.RunSQL(PROMOTE_EARLIEST_MEMBER, reverse_sql='SELECT 1'),
    ]
