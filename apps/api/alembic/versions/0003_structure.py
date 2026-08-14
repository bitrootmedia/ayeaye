"""teams, project groups, projects and project grants

Revision ID: 0003_structure
Revises: 0002_organisations
Create Date: Phase 2

Two things here are load-bearing and easy to lose in a later autogenerate:

* `ck_project_members_one_principal` — `num_nonnulls(user_id, team_id) = 1`.
  A grant names a person **or** a team; without this a row could name both and
  every visibility query would have to decide which one wins.
* the two partial unique indexes on `project_members`. One grant per principal
  per project, partial because the other column is NULL on every row and NULLs
  never collide.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_structure"
down_revision = "0002_organisations"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _timestamps():
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organisation_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "name", name="uq_teams_org_name"),
    )
    op.create_index(op.f("ix_teams_organisation_id"), "teams", ["organisation_id"])

    op.create_table(
        "team_members",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("team_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_members"),
    )
    op.create_index(op.f("ix_team_members_team_id"), "team_members", ["team_id"])
    op.create_index(op.f("ix_team_members_user_id"), "team_members", ["user_id"])

    op.create_table(
        "project_groups",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organisation_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "name", name="uq_project_groups_org_name"),
    )
    op.create_index(
        op.f("ix_project_groups_organisation_id"), "project_groups", ["organisation_id"]
    )

    op.create_table(
        "projects",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organisation_id", UUID, nullable=False),
        sa.Column("project_group_id", UUID, nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_user_id", UUID, nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        # SET NULL: deleting a folder must not delete the work inside it.
        sa.ForeignKeyConstraint(
            ["project_group_id"], ["project_groups.id"], ondelete="SET NULL"
        ),
        # RESTRICT: a project with no owner is one nobody can administer.
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_organisation_id"), "projects", ["organisation_id"])
    op.create_index(op.f("ix_projects_project_group_id"), "projects", ["project_group_id"])
    op.create_index(op.f("ix_projects_owner_user_id"), "projects", ["owner_user_id"])

    op.create_table(
        "project_members",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("team_id", UUID, nullable=True),
        sa.Column("level", sa.String(length=16), server_default="read", nullable=False),
        sa.Column("granted_by_user_id", UUID, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, team_id) = 1", name="ck_project_members_one_principal"
        ),
        sa.CheckConstraint("level IN ('read', 'write')", name="ck_project_members_level"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_members_project_id"), "project_members", ["project_id"])
    op.create_index(op.f("ix_project_members_user_id"), "project_members", ["user_id"])
    op.create_index(op.f("ix_project_members_team_id"), "project_members", ["team_id"])
    op.create_index(
        "uq_project_members_user",
        "project_members",
        ["project_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_project_members_team",
        "project_members",
        ["project_id", "team_id"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("project_members")
    op.drop_table("projects")
    op.drop_table("project_groups")
    op.drop_table("team_members")
    op.drop_table("teams")
