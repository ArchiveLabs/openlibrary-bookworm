"""initial schema: import_batch and import_item

Revision ID: 0001
Revises:
Create Date: 2026-05-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_batch",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column("submitter", sa.Text),
        sa.Column(
            "submit_time",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_import_batch_submitter", "import_batch", ["submitter"])
    op.create_index("ix_import_batch_submit_time", "import_batch", ["submit_time"])

    op.create_table(
        "import_item",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("import_batch.id"), nullable=False),
        sa.Column(
            "added_time",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("import_time", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("error", sa.Text),
        sa.Column("source_id", sa.Text),
        sa.Column("data", JSONB),
        sa.Column("ol_key", sa.Text),
        sa.Column("submitter", sa.Text),
    )
    op.create_index("ix_import_item_batch_id", "import_item", ["batch_id"])
    op.create_index("ix_import_item_status_added", "import_item", ["status", "added_time"])
    op.create_index("ix_import_item_source_id", "import_item", ["source_id"])
    op.create_unique_constraint(
        "uq_import_item_batch_source", "import_item", ["batch_id", "source_id"]
    )


def downgrade() -> None:
    op.drop_table("import_item")
    op.drop_table("import_batch")
