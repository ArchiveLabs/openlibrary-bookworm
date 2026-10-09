"""Use Procrastinate jobs as the source of import execution status."""

import sqlalchemy as sa
from alembic import op

revision = "d391b724e608"
down_revision = "c728ea61f205"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL search_path TO procrastinate, public")
    op.add_column("import_items", sa.Column("procrastinate_job_id", sa.BigInteger()))
    op.create_foreign_key(
        "fk_item_procrastinate_job",
        "import_items",
        "procrastinate_jobs",
        ["procrastinate_job_id"],
        ["id"],
        referent_schema="procrastinate",
    )
    op.create_index(
        "ix_import_items_procrastinate_job_id", "import_items", ["procrastinate_job_id"]
    )
    op.execute("UPDATE import_items SET error_context = NULL WHERE error_context = 'null'::jsonb")
    op.execute("""
        UPDATE import_items AS item SET procrastinate_job_id = task.id
        FROM (
            SELECT DISTINCT ON (args->>'item_id') id, args->>'item_id' AS item_id
            FROM procrastinate.procrastinate_jobs
            WHERE task_name = 'imports:import_item'
            ORDER BY args->>'item_id', id DESC
        ) AS task
        WHERE item.id::text = task.item_id
    """)
    # Old tasks returned normally for permanent import failures; retain those outcomes.
    op.execute("""
        UPDATE procrastinate.procrastinate_jobs AS task SET status = 'failed'
        FROM import_items AS item
        WHERE item.procrastinate_job_id = task.id
          AND item.status = 'failed' AND task.status = 'succeeded'
    """)
    # Older completed/failed items may predate the queue; preserve their terminal state.
    op.execute("""
        WITH inserted AS (
            INSERT INTO procrastinate.procrastinate_jobs (queue_name, task_name, args, status)
            SELECT 'imports', 'imports:import_item', jsonb_build_object('item_id', id::text),
                   (CASE status WHEN 'completed' THEN 'succeeded' WHEN 'failed' THEN 'failed'
                                WHEN 'processing' THEN 'doing' ELSE 'todo' END)
                   ::procrastinate.procrastinate_job_status
            FROM import_items
            WHERE approved_at IS NOT NULL AND procrastinate_job_id IS NULL
            RETURNING id, args
        )
        UPDATE import_items AS item SET procrastinate_job_id = inserted.id
        FROM inserted WHERE item.id::text = inserted.args->>'item_id'
    """)
    op.drop_constraint("ck_item_status", "import_items", type_="check")
    op.drop_constraint("ck_item_approval", "import_items", type_="check")
    op.drop_index("ix_items_job_status_position", table_name="import_items")
    op.drop_column("import_items", "status")
    op.create_index("ix_items_job_position", "import_items", ["job_id", "position"])
    op.execute("SET LOCAL search_path TO public")


def downgrade():
    op.add_column("import_items", sa.Column("status", sa.String(32)))
    op.execute("""
        UPDATE import_items AS item SET status = CASE
            WHEN procrastinate_job_id IS NULL THEN
                CASE WHEN error_context IS NULL THEN 'pending_approval' ELSE 'failed' END
            ELSE (SELECT CASE task.status WHEN 'todo' THEN 'queued' WHEN 'doing' THEN 'processing'
                      WHEN 'succeeded' THEN 'completed' ELSE 'failed' END
                  FROM procrastinate.procrastinate_jobs AS task WHERE task.id = procrastinate_job_id)
            END
    """)
    op.alter_column("import_items", "status", nullable=False)
    op.create_check_constraint(
        "ck_item_status",
        "import_items",
        "status IN ('pending_approval','queued','processing','completed','failed')",
    )
    op.create_check_constraint(
        "ck_item_approval",
        "import_items",
        "status NOT IN ('queued','processing','completed') OR approved_at IS NOT NULL",
    )
    op.drop_index("ix_items_job_position", table_name="import_items")
    op.create_index(
        "ix_items_job_status_position", "import_items", ["job_id", "status", "position"]
    )
    op.drop_index("ix_import_items_procrastinate_job_id", table_name="import_items")
    op.drop_constraint("fk_item_procrastinate_job", "import_items", type_="foreignkey")
    op.drop_column("import_items", "procrastinate_job_id")
