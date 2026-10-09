"""Create import service tables"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9bde1fb40de7"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_project_user_name"),
    )
    op.create_index(op.f("ix_projects_user_id"), "projects", ["user_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_created_id", "jobs", ["created_at", "id"], unique=False)
    op.create_index(op.f("ix_jobs_project_id"), "jobs", ["project_id"], unique=False)
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"], unique=False)
    op.create_table(
        "import_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("attempt_limit", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_approval','queued','processing','completed','failed')",
            name="ck_item_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('queued','processing','completed') OR approved_at IS NOT NULL",
            name="ck_item_approval",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_limit >= attempt_count", name="ck_item_attempts"
        ),
        sa.CheckConstraint("position >= 0", name="ck_item_position"),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "position", name="uq_item_job_position"),
    )
    op.create_index(
        "ix_items_dispatch",
        "import_items",
        ["status", "next_attempt_at", "approved_at", "job_id", "position"],
        unique=False,
    )
    op.create_index(
        "ix_items_job_status_position",
        "import_items",
        ["job_id", "status", "position"],
        unique=False,
    )
    op.create_table(
        "import_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("error_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('success','failure','unknown')",
            name="ck_attempt_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["import_items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "attempt_number", name="uq_attempt_item_number"),
    )
    op.create_index("ix_attempts_unfinished", "import_attempts", ["finished_at"], unique=False)
    op.create_index(
        op.f("ix_import_attempts_item_id"), "import_attempts", ["item_id"], unique=False
    )
    op.create_table(
        "source_reservations",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_record", sa.String(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["import_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.PrimaryKeyConstraint("project_id", "source_record"),
    )
    op.create_index(
        op.f("ix_source_reservations_item_id"), "source_reservations", ["item_id"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_source_reservations_item_id"), table_name="source_reservations")
    op.drop_table("source_reservations")
    op.drop_index(op.f("ix_import_attempts_item_id"), table_name="import_attempts")
    op.drop_index("ix_attempts_unfinished", table_name="import_attempts")
    op.drop_table("import_attempts")
    op.drop_index("ix_items_job_status_position", table_name="import_items")
    op.drop_index("ix_items_dispatch", table_name="import_items")
    op.drop_table("import_items")
    op.drop_index(op.f("ix_jobs_user_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_project_id"), table_name="jobs")
    op.drop_index("ix_jobs_created_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_projects_user_id"), table_name="projects")
    op.drop_table("projects")
