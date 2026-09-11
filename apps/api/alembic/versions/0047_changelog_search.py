"""changelog_entries.description: a trigram index, so search is an index lookup

Revision ID: 0047_changelog_search
Revises: 0046_changelog
Create Date: Phase 9 follow-up

`gin_trgm_ops`, not the default operator class — it is what serves **both**
halves of `services/search.py::matches`: the leading-wildcard `ILIKE '%…%'`
and the `%>` word-similarity operator. Without it a changelog search is a
sequential scan over the organisation's whole history, which is exactly the
table most likely to be the longest one a self-hoster has after a few years.

The same shape as 0012's own index on `task_notes.body` — one column, one
GIN index, no partial clause: unlike a task description there is no
generated stripped-text column to index instead, because a changelog entry
is plain text and never HTML.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047_changelog_search"
down_revision: str | None = "0046_changelog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_changelog_entries_description_trgm "
        "ON changelog_entries USING gin (description gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_changelog_entries_description_trgm")
