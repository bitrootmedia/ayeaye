"""task descriptions become HTML, and search stops matching markup

Revision ID: 0015_rich_descriptions
Revises: 0014_dashboard
Create Date: Phase 10

`description` now holds sanitised HTML. On its own that would break search:
`ILIKE '%div%'` against markup matches every task in the database, and result
snippets would show tags instead of prose.

`description_text` is a **generated column** — Postgres strips the tags, so it
cannot drift from the description the way a column maintained in application
code would, and it needs no backfill, no trigger and no second write path.
`regexp_replace` is immutable, which is what makes it indexable at all.

Existing descriptions are plain text and are left exactly as they are. A
one-way conversion of everybody's data, to fix rendering, is a trade nobody
asked for; the renderer wraps them instead.
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_rich_descriptions"
down_revision = "0014_dashboard"
branch_labels = None
depends_on = None

# Tags to spaces, not to nothing: "<p>one</p><p>two</p>" must not become
# "onetwo" and match neither word.
STRIP = r"regexp_replace(coalesce(description, ''), '<[^>]*>', ' ', 'g')"


def upgrade() -> None:
    op.execute(f"ALTER TABLE tasks ADD COLUMN description_text text GENERATED ALWAYS AS ({STRIP}) STORED")
    op.execute(
        "CREATE INDEX ix_tasks_description_text_trgm ON tasks "
        "USING gin (description_text gin_trgm_ops)"
    )
    # The old index served searches against the raw column. Nothing reads it
    # now, and an unused GIN index is still maintained on every write.
    op.execute("DROP INDEX IF EXISTS ix_tasks_description_trgm")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX ix_tasks_description_trgm ON tasks USING gin (description gin_trgm_ops)"
    )
    op.execute("DROP INDEX IF EXISTS ix_tasks_description_text_trgm")
    op.drop_column("tasks", "description_text")
