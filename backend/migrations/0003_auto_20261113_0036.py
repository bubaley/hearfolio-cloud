from tortoise import migrations
from tortoise.migrations import operations as ops
from app.domains.organization.models import OrganizationRole
from tortoise import fields

class Migration(migrations.Migration):
    dependencies = [('models', '0002_auth_token_lifecycle')]

    initial = False

    operations = [
        ops.AddField(
            model_name='OrganizationUser',
            name='role',
            field=fields.CharEnumField(default=OrganizationRole.MEMBER, description='OWNER: owner\nADMIN: admin\nMEMBER: member', enum_type=OrganizationRole, max_length=16),
        ),
    ]
