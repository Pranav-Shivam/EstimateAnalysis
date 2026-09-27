"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skus",
        sa.Column("sku_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("list_price", sa.Float(), nullable=False),
        sa.Column("discontinued", sa.Boolean(), nullable=False),
        sa.Column("replaced_by", sa.Text(), sa.ForeignKey("skus.sku_id"), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("account_tier", sa.Text(), nullable=False),
    )
    op.create_table(
        "sites",
        sa.Column("site_id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("zip", sa.Text(), nullable=False),
    )
    op.create_table(
        "contracts",
        sa.Column("contract_id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=False),
        sa.Column("discount_category", sa.Text(), nullable=False),
        sa.Column("covered_categories", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=False),
    )
    op.create_table(
        "quote_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=True),
        sa.Column("site_id", sa.Text(), sa.ForeignKey("sites.site_id"), nullable=True),
        sa.Column("contract_id", sa.Text(), sa.ForeignKey("contracts.contract_id"), nullable=True),
        sa.Column("raw_email_text", sa.Text(), nullable=False),
        sa.Column("parsed_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_fingerprint", postgresql.JSONB(), nullable=False),
        sa.Column("style_fingerprint", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "dedupe_verdicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("quote_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quote_requests.id"), nullable=False),
        sa.Column("candidate_quote_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quote_requests.id"), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("content_jaccard", sa.Float(), nullable=False),
        sa.Column("style_jaccard", sa.Float(), nullable=False),
        sa.Column("signals_fired", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("dedupe_verdicts")
    op.drop_table("quote_requests")
    op.drop_table("contracts")
    op.drop_table("sites")
    op.drop_table("customers")
    op.drop_table("skus")
