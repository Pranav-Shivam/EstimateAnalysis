"""product families, projects, contacts, sku embeddings, community summaries

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "product_families",
        sa.Column("family_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
    )
    op.add_column("skus", sa.Column("family_id", sa.Text(), sa.ForeignKey("product_families.family_id"), nullable=True))
    op.create_table(
        "projects",
        sa.Column("project_id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=False),
        sa.Column("site_id", sa.Text(), sa.ForeignKey("sites.site_id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.UniqueConstraint("site_id", name="uq_projects_site_id"),
    )
    op.create_table(
        "contacts",
        sa.Column("contact_id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
    )
    op.create_table(
        "sku_embeddings",
        sa.Column("sku_id", sa.Text(), sa.ForeignKey("skus.sku_id"), primary_key=True),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "community_summaries",
        sa.Column("member_hash", sa.Text(), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("community_summaries")
    op.drop_table("sku_embeddings")
    op.drop_table("contacts")
    op.drop_table("projects")
    op.drop_column("skus", "family_id")
    op.drop_table("product_families")
