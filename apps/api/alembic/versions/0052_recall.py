"""recall: facts, tags on articles and facts, and pgvector embeddings

Revision ID: 0052_recall
Revises: 0051_timer_check_ins
Create Date: recall

Hand-written, for 0046's reason: autogenerate can't reflect the trigram
indexes or the CHECK constraints and wants to drop them.

**`embeddings` is only created where pgvector is installed**, and that is the
one conditional in this directory — twice: the extension may be missing, or
present but not ours to create (a managed instance's app role usually can't;
its admin can, once). Bringing your own Postgres is supported
(see the self-host-troubleshooting skill), and a managed instance without the
extension must still migrate: failing here would take the whole product down
over a feature that is optional by design, exactly as email is. Every managed
Postgres worth naming ships pgvector, and the bundled one does from
infra/postgres/Dockerfile, so this is the rare case — and recall checks for
the table at runtime (`services/embeddings.py::available`) and falls back to
text alone without it.

An operator who installs the extension afterwards gets the table by
re-running this migration: `alembic downgrade 0051_timer_check_ins` then
`upgrade head`. The downgrade drops `embeddings` only if it exists, and the
facts and tags it would also drop are why that is a step to take on purpose
rather than something `migrate` does on its own.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052_recall"
down_revision: str | None = "0051_timer_check_ins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _tag_table(name: str, anchor: str, anchor_table: str) -> None:
    op.create_table(
        name,
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            anchor,
            UUID,
            sa.ForeignKey(f"{anchor_table}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag_id", UUID, sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(anchor, "tag_id", name=f"uq_{name}_{anchor.removesuffix('_id')}_tag"),
    )
    op.create_index(f"ix_{name}_{anchor}", name, [anchor])
    op.create_index(f"ix_{name}_tag", name, ["tag_id"])


def upgrade() -> None:
    op.create_table(
        "facts",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("book_id", UUID, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_by_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("via", sa.String(80), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "superseded_by_fact_id",
            UUID,
            sa.ForeignKey("facts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("length(btrim(body)) > 0", name="ck_facts_body"),
        sa.CheckConstraint("length(body) <= 4000", name="ck_facts_body_length"),
        sa.CheckConstraint("superseded_by_fact_id <> id", name="ck_facts_not_self_superseded"),
    )
    op.create_index("ix_facts_book_id", "facts", ["book_id"])
    # Both halves of `search.matches` — see 0047.
    op.execute("CREATE INDEX ix_facts_body_trgm ON facts USING gin (body gin_trgm_ops)")

    _tag_table("article_tags", "article_id", "articles")
    _tag_table("fact_tags", "fact_id", "facts")

    available = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    ).first()
    if available is None:
        print(
            "0052_recall: pgvector is not installed on this Postgres, so the embeddings "
            "table was not created. Recall will use text search alone."
        )
        return

    # Available is not the same as allowed. On a managed instance (DigitalOcean,
    # RDS) pgvector is listed but only the admin role may create it, and an app
    # that connects as its own user fails here — which, outside a savepoint,
    # aborts the whole migration and the deploy with it. Same outcome as not
    # installed: text-only, and the operator creates it as admin and re-runs.
    bind = op.get_bind()
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except sa.exc.DBAPIError as exc:
        print(
            "0052_recall: pgvector is available but this role may not create it "
            f"({exc.orig}), so the embeddings table was not created. Recall will "
            "use text search alone. Run `CREATE EXTENSION vector` as an admin, "
            "then re-run this migration."
        )
        return
    op.execute(
        """
        CREATE TABLE embeddings (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            organisation_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            fact_id uuid REFERENCES facts(id) ON DELETE CASCADE,
            article_id uuid REFERENCES articles(id) ON DELETE CASCADE,
            task_id uuid REFERENCES tasks(id) ON DELETE CASCADE,
            chunk_index integer NOT NULL,
            content text NOT NULL,
            source_hash varchar(32) NOT NULL,
            model varchar(200) NOT NULL,
            embedding halfvec NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_embeddings_one_anchor
                CHECK (num_nonnulls(fact_id, article_id, task_id) = 1)
        )
        """
    )
    op.create_index("ix_embeddings_org_model", "embeddings", ["organisation_id", "model"])
    op.create_index("ix_embeddings_fact_id", "embeddings", ["fact_id"])
    op.create_index("ix_embeddings_article_id", "embeddings", ["article_id"])
    op.create_index("ix_embeddings_task_id", "embeddings", ["task_id"])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS embeddings")
    # The extension stays: something else may be using it, and dropping one
    # is not this migration's business.
    op.drop_table("fact_tags")
    op.drop_table("article_tags")
    op.drop_index("ix_facts_body_trgm", table_name="facts")
    op.drop_table("facts")
