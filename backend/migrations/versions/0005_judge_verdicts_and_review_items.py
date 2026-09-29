"""judge verdicts and review items

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_verdicts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("estimate_id", UUID(as_uuid=True), sa.ForeignKey("estimate_drafts.id"), nullable=False, index=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("dimensions", JSONB(), nullable=False),
        sa.Column("overall_confidence", sa.Float(), nullable=False),
        sa.Column("flagged_dimension", sa.Text(), nullable=False),
        sa.Column("trusted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "review_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("judge_verdict_id", UUID(as_uuid=True), sa.ForeignKey("judge_verdicts.id"), nullable=False, index=True),
        sa.Column("estimate_id", UUID(as_uuid=True), sa.ForeignKey("estimate_drafts.id"), nullable=False, index=True),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("line_index", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("review_items")
    op.drop_table("judge_verdicts")
