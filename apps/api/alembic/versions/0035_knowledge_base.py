"""knowledge base: books, articles, and article revisions

Revision ID: 0035_knowledge_base
Revises: 0034_oauth
Create Date: Phase 9 follow-up

Books and their grants are a straight copy of projects/project_members —
see models/knowledge_base.py. An article holds no content itself; every
edit is a new (or updated, while still the latest) article_revisions row,
and `body_text` is a generated column stripping HTML tags, the identical
`tasks.description_text` idiom (see 0015_rich_descriptions.py) so search
reads prose, not markup.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035_knowledge_base"
down_revision = "0034_oauth"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)

# Tags to spaces, not to nothing — the identical STRIP expression
# 0015_rich_descriptions.py uses for tasks.description_text.
STRIP = r"regexp_replace(coalesce(body, ''), '<[^>]*>', ' ', 'g')"


def upgrade() -> None:
    op.create_table(
        "books",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "organisation_id",
            UUID,
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "owner_user_id", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "created_by_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_books_organisation_id", "books", ["organisation_id"])
    op.create_index("ix_books_owner_user_id", "books", ["owner_user_id"])

    op.create_table(
        "book_members",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("book_id", UUID, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("team_id", UUID, sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True),
        sa.Column("level", sa.String(16), nullable=False, server_default="read"),
        sa.Column(
            "granted_by_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, team_id) = 1", name="ck_book_members_one_principal"
        ),
        sa.CheckConstraint("level IN ('read', 'write')", name="ck_book_members_level"),
    )
    op.create_index("ix_book_members_book_id", "book_members", ["book_id"])
    op.create_index("ix_book_members_user_id", "book_members", ["user_id"])
    op.create_index("ix_book_members_team_id", "book_members", ["team_id"])
    op.create_index(
        "uq_book_members_user",
        "book_members",
        ["book_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_book_members_team",
        "book_members",
        ["book_id", "team_id"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL"),
    )

    op.create_table(
        "articles",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("book_id", UUID, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "owner_user_id", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "created_by_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_articles_book_id", "articles", ["book_id"])
    op.create_index("ix_articles_owner_user_id", "articles", ["owner_user_id"])

    op.create_table(
        "article_revisions",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "article_id", UUID, sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(300), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "edited_by_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_article_revisions_article_id", "article_revisions", ["article_id"])
    op.execute(
        f"ALTER TABLE article_revisions ADD COLUMN body_text text "
        f"GENERATED ALWAYS AS ({STRIP}) STORED"
    )
    op.execute(
        "CREATE INDEX ix_article_revisions_title_trgm ON article_revisions "
        "USING gin (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_article_revisions_body_text_trgm ON article_revisions "
        "USING gin (body_text gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_table("article_revisions")
    op.drop_table("articles")
    op.drop_table("book_members")
    op.drop_table("books")
