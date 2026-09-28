"""pricing data and estimate drafts

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("skus", "list_price", existing_type=sa.Float(), nullable=True)
    op.add_column("contracts", sa.Column("discount_pct", sa.Float(), nullable=False, server_default="0"))
    op.create_table(
        "sku_requirements",
        sa.Column("sku_id", sa.Text(), sa.ForeignKey("skus.sku_id"), primary_key=True),
        sa.Column("required_sku_id", sa.Text(), sa.ForeignKey("skus.sku_id"), primary_key=True),
    )
    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("sku_id", sa.Text(), sa.ForeignKey("skus.sku_id"), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("quoted_on", sa.Date(), nullable=False),
    )
    op.create_table(
        "estimate_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("quote_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quote_requests.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("draft", postgresql.JSONB(), nullable=True),
        sa.Column("violations", postgresql.JSONB(), nullable=False),
        sa.Column("iterations", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("estimate_drafts")
    op.drop_table("price_history")
    op.drop_table("sku_requirements")
    op.drop_column("contracts", "discount_pct")
    op.execute("UPDATE skus SET list_price = 0 WHERE list_price IS NULL")
    op.alter_column("skus", "list_price", existing_type=sa.Float(), nullable=False)
