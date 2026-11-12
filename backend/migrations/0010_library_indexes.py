from tortoise import migrations
from tortoise.migrations import operations as ops

# Foreign keys are not indexed by PostgreSQL on their own; these back the per-recording / per-project / per-user
# lookups and the recordings list (organization, newest first, id as the tiebreaker). Portable SQL (SQLite too).
INDEXES = {
    'recording_event_recording_id': 'recording_event (recording_id)',
    'recording_result_recording_id': 'recording_result (recording_id)',
    'recording_project_id': 'recording (project_id)',
    'recording_suggested_project_id': 'recording (suggested_project_id)',
    'recording_tag_tag_id': 'recording_tag (tag_id)',
    'project_member_user_id': 'project_member (user_id)',
    'recording_org_recorded_at_id': 'recording (organization_id, recorded_at DESC, id)',
}


class Migration(migrations.Migration):
    dependencies = [('models', '0009_backfill_organization_owners')]

    initial = False

    operations = [
        ops.RunSQL(
            [f'CREATE INDEX IF NOT EXISTS {name} ON {target}' for name, target in INDEXES.items()],
            reverse_sql=[f'DROP INDEX IF EXISTS {name}' for name in INDEXES],
        ),
    ]
