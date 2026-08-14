"""organisations and membership (which is also invitations)

Revision ID: 0002_organisations
Revises: 0001_users
Create Date: Phase 1

The two partial unique indexes are the interesting part:

* `uq_org_members_org_user` — one membership per person per organisation, but
  only where there IS a person. Invitations to addresses without an account
  have a NULL user_id and several must be able to coexist.
* `uq_org_members_org_invited_email` — one *outstanding* invitation per address,
  scoped to `status = 'invited'` so re-inviting someone who left doesn't
  collide with their historical row.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_organisations"
down_revision = "0001_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organisations_slug"), "organisations", ["slug"], unique=True)

    op.create_table(
        "organisation_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(length=16), server_default="member", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="invited", nullable=False),
        sa.Column("invited_email", sa.String(length=320), nullable=True),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invite_token", sa.String(length=64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('member', 'admin', 'owner')", name="ck_org_members_role"
        ),
        sa.CheckConstraint(
            "status IN ('invited', 'active')", name="ck_org_members_status"
        ),
        sa.CheckConstraint(
            "status <> 'active' OR user_id IS NOT NULL",
            name="ck_org_members_active_has_user",
        ),
        sa.CheckConstraint(
            "status <> 'invited' OR invited_email IS NOT NULL",
            name="ck_org_members_invited_has_email",
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_organisation_members_organisation_id"),
        "organisation_members",
        ["organisation_id"],
    )
    op.create_index(
        op.f("ix_organisation_members_invite_token"),
        "organisation_members",
        ["invite_token"],
        unique=True,
    )
    op.create_index(
        "ix_org_members_invited_email", "organisation_members", ["invited_email"]
    )
    op.create_index(
        "uq_org_members_org_user",
        "organisation_members",
        ["organisation_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_org_members_org_invited_email",
        "organisation_members",
        ["organisation_id", "invited_email"],
        unique=True,
        postgresql_where=sa.text("status = 'invited'"),
    )


def downgrade() -> None:
    op.drop_table("organisation_members")
    op.drop_index(op.f("ix_organisations_slug"), table_name="organisations")
    op.drop_table("organisations")
