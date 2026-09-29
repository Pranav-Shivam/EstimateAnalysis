"""review resolution columns and eval cases

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_items", sa.Column("outcome", sa.Text(), nullable=True))
    op.add_column("review_items", sa.Column("correction", JSONB(), nullable=True))
    op.add_column("review_items", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "eval_cases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_review_item_id", UUID(as_uuid=True), sa.ForeignKey("review_items.id"), nullable=True),
        sa.Column("case_id", sa.Text(), nullable=False, unique=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("estimate_status", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("eval_cases")
    op.drop_column("review_items", "resolved_at")
    op.drop_column("review_items", "correction")
    op.drop_column("review_items", "outcome")
