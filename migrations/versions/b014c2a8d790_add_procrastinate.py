"""Install Procrastinate 3.10.0 and enqueue existing approved items."""

from pathlib import Path

from alembic import op

revision = "b014c2a8d790"
down_revision = "9bde1fb40de7"
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
    op.execute("""
        SELECT procrastinate_defer_jobs_v1(ARRAY(
            SELECT ROW('imports', 'imports:import_item', 0, id::text, NULL,
                       jsonb_build_object('item_id', id::text), next_attempt_at)
                ::procrastinate_job_to_defer_v1
            FROM public.import_items
            WHERE status = 'queued' AND approved_at IS NOT NULL
            ORDER BY approved_at, job_id, position
        ))
    """)
    op.execute("SET LOCAL search_path TO public")


def downgrade():
    op.execute("DROP SCHEMA procrastinate CASCADE")
