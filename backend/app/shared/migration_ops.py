from tortoise.migrations import operations as ops
from tortoise.migrations.schema_editor.base import BaseSchemaEditor
from tortoise.migrations.schema_generator.state import State


class PostgresRunSQL(ops.RunSQL):
    """
    `RunSQL` that runs on PostgreSQL only (GIN indexes, generated columns) and is a no-op elsewhere, so a SQLite
    database can still be migrated. Use plain `RunSQL` for portable statements.
    """

    @staticmethod
    def _is_postgres(state_editor: BaseSchemaEditor | None) -> bool:
        return state_editor is not None and state_editor.client.capabilities.dialect == 'postgres'

    async def database_forward(
        self, app_label: str, old_state: State, new_state: State, state_editor: BaseSchemaEditor | None = None
    ) -> None:
        if self._is_postgres(state_editor):
            await super().database_forward(app_label, old_state, new_state, state_editor)

    async def database_backward(
        self, app_label: str, old_state: State, new_state: State, state_editor: BaseSchemaEditor | None = None
    ) -> None:
        if self._is_postgres(state_editor):
            await super().database_backward(app_label, old_state, new_state, state_editor)
