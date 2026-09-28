"""index the estimate draft and price history lookup columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28

"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_estimate_drafts_quote_request_id", "estimate_drafts", ["quote_request_id"])
    op.create_index("ix_price_history_sku_id", "price_history", ["sku_id"])


def downgrade() -> None:
    op.drop_index("ix_price_history_sku_id", table_name="price_history")
    op.drop_index("ix_estimate_drafts_quote_request_id", table_name="estimate_drafts")
