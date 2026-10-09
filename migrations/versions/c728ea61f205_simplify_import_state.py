"""Keep import outcomes on items and delegate retry accounting to Procrastinate."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c728ea61f205"
down_revision = "b014c2a8d790"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("import_attempts")
    op.drop_index("ix_items_dispatch", table_name="import_items")
    op.drop_constraint("ck_item_attempts", "import_items", type_="check")
    for column in ("attempt_count", "attempt_limit", "next_attempt_at"):
        op.drop_column("import_items", column)


def downgrade():
    op.add_column(
        "import_items", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "import_items", sa.Column("attempt_limit", sa.Integer(), nullable=False, server_default="5")
    )
    op.add_column("import_items", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_item_attempts", "import_items", "attempt_count >= 0 AND attempt_limit >= attempt_count"
    )
    op.create_index(
        "ix_items_dispatch",
        "import_items",
        ["status", "next_attempt_at", "approved_at", "job_id", "position"],
    )
    op.create_table(
        "import_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("import_items.id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(16)),
        sa.Column("error_context", postgresql.JSONB()),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("item_id", "attempt_number", name="uq_attempt_item_number"),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('success','failure','unknown')",
            name="ck_attempt_outcome",
        ),
    )
    op.create_index("ix_attempts_unfinished", "import_attempts", ["finished_at"])
    op.create_index("ix_import_attempts_item_id", "import_attempts", ["item_id"])
    # History cannot be restored; seed unfinished rows so old workers can recover.
    op.execute("""
        INSERT INTO import_attempts (id, item_id, attempt_number, started_at, simulated)
        SELECT id, id, 1, updated_at, false FROM import_items WHERE status = 'processing'
    """)
    op.execute("UPDATE import_items SET attempt_count = 1 WHERE status = 'processing'")
    for column in ("attempt_count", "attempt_limit"):
        op.alter_column("import_items", column, server_default=None)
