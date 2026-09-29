"""procrastinate job queue schema

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29

Applies the schema.sql shipped inside the installed procrastinate package (the same SQL `procrastinate schema
--apply` runs), so the queue's tables live under Alembic like every other table. schema.sql is the full schema of
that procrastinate release. A later procrastinate upgrade that ships its own SQL migrations needs those applied
as a new revision; re-running this one would not pick them up.

"""
from alembic import op
from procrastinate.schema import SchemaManager

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_TABLES = ("procrastinate_events", "procrastinate_periodic_defers", "procrastinate_jobs", "procrastinate_workers")
_TYPES = ("procrastinate_job_to_defer_v1", "procrastinate_job_event_type", "procrastinate_job_status")


def upgrade() -> None:
    # Straight to the driver cursor with no parameters: psycopg then sends the file as one simple query, which
    # allows many statements and leaves its '%' characters alone. SQLAlchemy's text() would treat ':name' as a bind.
    with op.get_bind().connection.dbapi_connection.cursor() as cursor:
        cursor.execute(SchemaManager.get_schema())


def downgrade() -> None:
    # Tables first (their triggers go with them), then every procrastinate function whatever its versioned
    # suffix, then the types the functions used.
    op.execute(f"DROP TABLE IF EXISTS {', '.join(_TABLES)} CASCADE")
    op.execute(
        """
        DO $$
        DECLARE fn regprocedure;
        BEGIN
            FOR fn IN SELECT oid::regprocedure FROM pg_proc WHERE proname LIKE 'procrastinate\\_%' LOOP
                EXECUTE 'DROP FUNCTION ' || fn || ' CASCADE';
            END LOOP;
        END
        $$
        """
    )
    op.execute(f"DROP TYPE IF EXISTS {', '.join(_TYPES)} CASCADE")
