"""personal access tokens, so a program can act as a person

Revision ID: 0016_access_tokens
Revises: 0015_rich_descriptions
Create Date: Phase 11

The secret is **hashed**; the plaintext is shown once at creation and never
again. A token recoverable from the database is a token that a backup hands to
whoever holds the backup.

`prefix` keeps the first few characters in the clear, which is the only way
"which of these three do I revoke" is answerable without being able to
reconstruct any of them.

Scope is two values on purpose. "Let an assistant read my work" and "let it
create things in my name" are different decisions, and most people only want
the first.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_access_tokens"
down_revision = "0015_rich_descriptions"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("scope", sa.String(length=8), nullable=False, server_default="read"),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("scope IN ('read', 'write')", name="ck_pat_scope"),
    )
    op.create_index("ix_personal_access_tokens_user_id", "personal_access_tokens", ["user_id"])
    # Every MCP call is a lookup by hash, so it must be an index hit rather
    # than a scan over every token in the installation.
    op.create_index(
        "ix_personal_access_tokens_token_hash",
        "personal_access_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("personal_access_tokens")
