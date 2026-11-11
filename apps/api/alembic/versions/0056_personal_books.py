"""personal books: one private memory book per person per organisation

Revision ID: 0056_personal_books
Revises: 0055_chats
Create Date: personal books

See `models/knowledge_base.py`'s `Book` docstring. `books.is_personal`
defaults to false, so every existing book is unchanged. The partial unique
index is what makes `services/books.py::personal_book`'s get-or-create safe
against two first `remember` calls racing each other.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056_personal_books"
down_revision: str | None = "0055_chats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column("is_personal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "uq_books_personal_owner",
        "books",
        ["organisation_id", "owner_user_id"],
        unique=True,
        postgresql_where=sa.text("is_personal"),
    )


def downgrade() -> None:
    # Dropping the flag would turn every personal book into an ordinary one,
    # which organisation admins can open. Refuse to do that silently.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM books WHERE is_personal) THEN "
        "RAISE EXCEPTION 'personal books exist: delete them first, or they would "
        "become visible to organisation admins'; END IF; END $$"
    )
    op.drop_index("uq_books_personal_owner", table_name="books")
    op.drop_column("books", "is_personal")
