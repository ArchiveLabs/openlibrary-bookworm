"""Install the frozen Procrastinate 3.10.0 schema."""

from pathlib import Path

from alembic import op

revision = "b014c2a8d790"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA procrastinate")
    op.execute("SET LOCAL search_path TO procrastinate, public")
    # Snapshot the library schema so this migration stays stable across dependency upgrades.
    schema = Path(__file__).parents[1] / "procrastinate_schema.sql"
    connection = op.get_bind().connection.driver_connection
    with connection.cursor() as cursor:
        cursor.execute(schema.read_text())
    op.execute("SET LOCAL search_path TO public")


def downgrade():
    op.execute("DROP SCHEMA procrastinate CASCADE")
