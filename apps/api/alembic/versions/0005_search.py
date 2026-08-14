"""pg_trgm and the GIN indexes that make fuzzy search fast

Revision ID: 0005_search
Revises: 0004_tasks
Create Date: Phase 4b

`pg_trgm` is what turns a leading-wildcard `ILIKE '%foo%'` from a sequential
scan into an index lookup, and it supplies `word_similarity()` for typo
tolerance. Without these indexes the search still *works* — and gets slower in
direct proportion to how much work the organisation has done, which is exactly
the moment search starts to matter.

Indexed on the description columns as well as the titles. They're longer and
the index is correspondingly bigger, but a search that only looks at titles
misses "the task where I wrote down the part number", which is most of why
people search at all.

`CREATE EXTENSION` needs superuser. The `POSTGRES_USER` in the compose file is
the superuser of its own instance, so this is fine here; a managed database
where that isn't true needs the extension enabled by the provider first.
"""

from alembic import op

revision = "0005_search"
down_revision = "0004_tasks"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_tasks_title_trgm", "tasks", "title"),
    ("ix_tasks_description_trgm", "tasks", "description"),
    ("ix_projects_name_trgm", "projects", "name"),
    ("ix_projects_description_trgm", "projects", "description"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in INDEXES:
        # gin_trgm_ops, not the default: it's what serves both ILIKE and
        # word_similarity from the same index.
        op.execute(f"CREATE INDEX {name} ON {table} USING gin ({column} gin_trgm_ops)")


def downgrade() -> None:
    for name, _table, _column in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    # The extension is deliberately left in place: something else may have
    # started using it, and dropping it would take their indexes with it.
