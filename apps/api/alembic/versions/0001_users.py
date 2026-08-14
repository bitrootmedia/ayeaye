"""users — the local mirror of SuperTokens identity

Revision ID: 0001_users
Revises:
Create Date: Phase 0

`uuidv7()` is a Postgres 18 builtin. Every primary key in this schema is a
server-generated UUIDv7: time-ordered (so it indexes like a sequence and sorts
chronologically) without leaking a row count the way a bigserial does.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("supertokens_user_id", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_users_supertokens_user_id"),
        "users",
        ["supertokens_user_id"],
        unique=True,
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_supertokens_user_id"), table_name="users")
    op.drop_table("users")
