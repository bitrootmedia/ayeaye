"""oauth 2.1: dynamic client registration for MCP connectors

Revision ID: 0034_oauth
Revises: 0033_sparks
Create Date: Phase 9 follow-up

Four tables — see models/oauth.py and services/oauth.py for the reasoning.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034_oauth"
down_revision = "0033_sparks"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("client_secret_hash", sa.String(64), nullable=True),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("redirect_uris", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "token_endpoint_auth_method",
            sa.String(20),
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "grant_types",
            sa.String(80),
            nullable=False,
            server_default="authorization_code refresh_token",
        ),
        sa.Column("scope", sa.String(32), nullable=False, server_default="read"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "token_endpoint_auth_method IN ('none', 'client_secret_post')",
            name="ck_oauth_clients_auth_method",
        ),
        sa.CheckConstraint("scope IN ('read', 'write')", name="ck_oauth_clients_scope"),
    )

    op.create_table(
        "oauth_grants",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "client_id", UUID, sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("client_id", "user_id", name="uq_oauth_grants_client_user"),
        sa.CheckConstraint("scope IN ('read', 'write')", name="ck_oauth_grants_scope"),
    )
    op.create_index("ix_oauth_grants_user_id", "oauth_grants", ["user_id"])

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column(
            "client_id", UUID, sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "grant_id", UUID, sa.ForeignKey("oauth_grants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_oauth_authorization_codes_code_hash",
        "oauth_authorization_codes",
        ["code_hash"],
        unique=True,
    )

    op.create_table(
        "oauth_access_tokens",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "grant_id", UUID, sa.ForeignKey("oauth_grants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("access_token_hash", sa.String(64), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_oauth_access_tokens_grant_id", "oauth_access_tokens", ["grant_id"])
    op.create_index(
        "ix_oauth_access_tokens_access_token_hash",
        "oauth_access_tokens",
        ["access_token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_oauth_access_tokens_refresh_token_hash",
        "oauth_access_tokens",
        ["refresh_token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("oauth_access_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_grants")
    op.drop_table("oauth_clients")
