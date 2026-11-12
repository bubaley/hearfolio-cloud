from tortoise import migrations
from tortoise.migrations import operations as ops
import functools
from app.domains.library.models import ProjectSuggestionState, RecordingEventKind, RecordingSource, RecordingStatus, RecordingVisibility, TagColor, TitleSource, UploadState
from json import dumps, loads
from tortoise.contrib.postgres.fields import TSVectorField
from tortoise.fields.base import OnDelete
from uuid import uuid4
from tortoise import fields
from app.shared.migration_ops import PostgresRunSQL

class Migration(migrations.Migration):
    dependencies = [('models', '0005_auto_20261113_0053')]

    initial = False

    operations = [
        ops.CreateModel(
            name='Project',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('organization', fields.ForeignKeyField('models.Organization', source_field='organization_id', db_constraint=True, to_field='id', related_name='projects', on_delete=OnDelete.CASCADE)),
                ('name', fields.CharField(max_length=255)),
                ('emoji', fields.CharField(null=True, max_length=32)),
                ('description', fields.TextField(default='', unique=False)),
                ('is_private', fields.BooleanField(default=False)),
                ('created_by', fields.ForeignKeyField('models.User', source_field='created_by_id', null=True, db_constraint=True, to_field='id', related_name='created_projects', on_delete=OnDelete.SET_NULL)),
                ('archived_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
            ],
            options={'table': 'project', 'app': 'models', 'pk_attr': 'id'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='ProjectMember',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('project', fields.ForeignKeyField('models.Project', source_field='project_id', db_constraint=True, to_field='id', related_name='members', on_delete=OnDelete.CASCADE)),
                ('user', fields.ForeignKeyField('models.User', source_field='user_id', db_constraint=True, to_field='id', related_name='project_memberships', on_delete=OnDelete.CASCADE)),
            ],
            options={'table': 'project_member', 'app': 'models', 'unique_together': (('project', 'user'),), 'pk_attr': 'id'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='Tag',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('organization', fields.ForeignKeyField('models.Organization', source_field='organization_id', db_constraint=True, to_field='id', related_name='tags', on_delete=OnDelete.CASCADE)),
                ('name', fields.CharField(max_length=64)),
                ('name_key', fields.CharField(max_length=64)),
                ('color', fields.CharEnumField(default=TagColor.GRAY, description='GRAY: gray\nBROWN: brown\nORANGE: orange\nYELLOW: yellow\nGREEN: green\nBLUE: blue\nPURPLE: purple\nPINK: pink\nRED: red', enum_type=TagColor, max_length=16)),
            ],
            options={'table': 'tag', 'app': 'models', 'unique_together': (('organization', 'name_key'),), 'pk_attr': 'id'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='Recording',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('organization', fields.ForeignKeyField('models.Organization', source_field='organization_id', db_constraint=True, to_field='id', related_name='recordings', on_delete=OnDelete.CASCADE)),
                ('client_id', fields.UUIDField()),
                ('created_by', fields.ForeignKeyField('models.User', source_field='created_by_id', null=True, db_constraint=True, to_field='id', related_name='recordings', on_delete=OnDelete.SET_NULL)),
                ('visibility', fields.CharEnumField(default=RecordingVisibility.ORGANIZATION, description='ORGANIZATION: organization\nPERSONAL: personal', enum_type=RecordingVisibility, max_length=16)),
                ('project', fields.ForeignKeyField('models.Project', source_field='project_id', null=True, db_constraint=True, to_field='id', related_name='recordings', on_delete=OnDelete.SET_NULL)),
                ('suggested_project', fields.ForeignKeyField('models.Project', source_field='suggested_project_id', null=True, db_constraint=True, to_field='id', related_name='suggested_recordings', on_delete=OnDelete.SET_NULL)),
                ('project_suggestion_state', fields.CharEnumField(default=ProjectSuggestionState.NONE, description='NONE: none\nPENDING: pending\nACCEPTED: accepted\nDISMISSED: dismissed', enum_type=ProjectSuggestionState, max_length=16)),
                ('tags', fields.ManyToManyField('models.Tag', unique=True, db_constraint=True, through='recording_tag', forward_key='tag_id', backward_key='recording_id', related_name='recordings', on_delete=OnDelete.CASCADE)),
                ('title', fields.CharField(default='', max_length=255)),
                ('title_source', fields.CharEnumField(default=TitleSource.AUTO, description='AUTO: auto\nUSER: user', enum_type=TitleSource, max_length=8)),
                ('recorded_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=False)),
                ('duration_ms', fields.BigIntField(default=0)),
                ('source', fields.CharEnumField(default=RecordingSource.DESKTOP, description='DESKTOP: desktop\nANDROID: android\nWEB: web\nIMPORT: import', enum_type=RecordingSource, max_length=16)),
                ('audio_key', fields.CharField(max_length=512)),
                ('audio_size', fields.BigIntField()),
                ('audio_mime', fields.CharField(max_length=128)),
                ('original_filename', fields.CharField(default='', max_length=255)),
                ('upload_state', fields.CharEnumField(default=UploadState.PENDING, description='PENDING: pending\nUPLOADING: uploading\nUPLOADED: uploaded\nFAILED: failed', enum_type=UploadState, max_length=16)),
                ('upload_id', fields.CharField(null=True, max_length=1024)),
                ('upload_part_size', fields.BigIntField(null=True)),
                ('status', fields.CharEnumField(default=RecordingStatus.AWAITING_UPLOAD, description='AWAITING_UPLOAD: awaiting_upload\nQUEUED: queued\nTRANSCRIBING: transcribing\nTRANSCRIBED: transcribed\nFAILED: failed', enum_type=RecordingStatus, max_length=16)),
                ('progress', fields.SmallIntField(default=0)),
                ('segments_done', fields.IntField(default=0)),
                ('segments_total', fields.IntField(default=0)),
                ('transcript_text', fields.TextField(default='', unique=False)),
                ('transcript_segments', fields.JSONField(default=list, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
                ('transcription_model', fields.CharField(null=True, max_length=255)),
                ('language', fields.CharField(null=True, max_length=32)),
                ('error_code', fields.CharField(null=True, max_length=64)),
                ('error_message', fields.CharField(null=True, max_length=2000)),
                ('search_vector', TSVectorField(generated=True, null=True, source_fields=('title', 'transcript_text'), config='simple', stored=True)),
                ('deleted_at', fields.DatetimeField(null=True, db_index=True, auto_now=False, auto_now_add=False)),
            ],
            options={'table': 'recording', 'app': 'models', 'unique_together': (('organization', 'client_id'),), 'pk_attr': 'id'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='RecordingEvent',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('recording', fields.ForeignKeyField('models.Recording', source_field='recording_id', db_constraint=True, to_field='id', related_name='events', on_delete=OnDelete.CASCADE)),
                ('actor', fields.ForeignKeyField('models.User', source_field='actor_id', null=True, db_constraint=True, to_field='id', related_name='recording_events', on_delete=OnDelete.SET_NULL)),
                ('kind', fields.CharEnumField(description='CREATED: created\nUPLOADED: uploaded\nTRANSCRIBED: transcribed\nFAILED: failed\nRENAMED: renamed\nMOVED: moved\nTAGGED: tagged\nSHARED: shared\nUNSHARED: unshared\nRESULT_CREATED: result_created\nRESTORED: restored\nDELETED: deleted', enum_type=RecordingEventKind, max_length=32)),
                ('data', fields.JSONField(default=dict, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
            ],
            options={'table': 'recording_event', 'app': 'models', 'pk_attr': 'id'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='ShareLink',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(db_index=True, auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('recording', fields.ForeignKeyField('models.Recording', source_field='recording_id', db_constraint=True, to_field='id', related_name='share_links', on_delete=OnDelete.CASCADE)),
                ('token', fields.CharField(unique=True, max_length=64)),
                ('include_audio', fields.BooleanField(default=True)),
                ('include_transcript', fields.BooleanField(default=True)),
                ('result_ids', fields.JSONField(default=list, encoder=functools.partial(dumps, separators=(',', ':')), decoder=loads)),
                ('expires_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ('revoked_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ('created_by', fields.ForeignKeyField('models.User', source_field='created_by_id', null=True, db_constraint=True, to_field='id', related_name='share_links', on_delete=OnDelete.SET_NULL)),
                ('views', fields.IntField(default=0)),
            ],
            options={'table': 'share_link', 'app': 'models', 'pk_attr': 'id'},
            bases=['BaseModel'],
        ),
        # Not declared on the models (SQLite test schemas are generated from the models). GIN is PostgreSQL-only;
        # the other two are portable, so a SQLite database still migrates.
        PostgresRunSQL(
            'CREATE INDEX recording_search_vector_gin ON recording USING GIN (search_vector);',
            reverse_sql='DROP INDEX IF EXISTS recording_search_vector_gin;',
        ),
        ops.RunSQL(
            [
                'CREATE INDEX recording_org_updated_id ON recording (organization_id, updated_at, id)',
                'CREATE UNIQUE INDEX share_link_one_active ON share_link (recording_id) WHERE revoked_at IS NULL',
            ],
            reverse_sql=['DROP INDEX IF EXISTS recording_org_updated_id', 'DROP INDEX IF EXISTS share_link_one_active'],
        ),
    ]
