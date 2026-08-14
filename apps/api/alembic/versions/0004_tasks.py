"""tasks, per-task grants, the event history and the notification inbox

Revision ID: 0004_tasks
Revises: 0003_structure
Create Date: Phase 4

Two shapes worth reading before changing anything here:

* `tasks.project_id` is **nullable**. NULL means a loose task, owned by the
  organisation rather than a project, and deliberately not visible to everyone
  in it. `services/access.py` resolves it with a correlated subquery precisely
  so a NULL doesn't drop the row from the result.
* `tasks.closed_at` is separate from `tasks.status`. Closing is not a status,
  so "closed while still `blocker`" is expressible.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_tasks"
down_revision = "0003_structure"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
STATUSES = "('todo', 'in_progress', 'on_hold', 'review', 'blocker')"
EVENT_KINDS = (
    "('created', 'status_changed', 'closed', 'reopened', 'owner_changed', "
    "'action_required_set', 'action_required_cleared', 'moved', 'due_changed', "
    "'renamed', 'access_granted', 'access_revoked')"
)
NOTIFICATION_KINDS = (
    "('task_action_required', 'task_owner_changed', 'task_closed', "
    "'task_shared', 'project_shared')"
)


def _now(name: str):
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organisation_id", UUID, nullable=False),
        sa.Column("project_id", UUID, nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="todo", nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", UUID, nullable=True),
        sa.Column("owner_user_id", UUID, nullable=False),
        sa.Column("action_required_user_id", UUID, nullable=True),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_tasks_status"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        # RESTRICT: a task with no owner is one nobody may close. Removing a
        # member reassigns first — see services/organisations.remove_member.
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["action_required_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_organisation_id"), "tasks", ["organisation_id"])
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"])
    op.create_index(op.f("ix_tasks_owner_user_id"), "tasks", ["owner_user_id"])
    op.create_index(
        op.f("ix_tasks_action_required_user_id"), "tasks", ["action_required_user_id"]
    )
    op.create_index("ix_tasks_project_open", "tasks", ["project_id", "closed_at"])
    op.create_index("ix_tasks_org_open", "tasks", ["organisation_id", "closed_at"])

    op.create_table(
        "task_grants",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("team_id", UUID, nullable=True),
        sa.Column("level", sa.String(length=16), server_default="read", nullable=False),
        sa.Column("granted_by_user_id", UUID, nullable=True),
        _now("created_at"),
        sa.CheckConstraint(
            "num_nonnulls(user_id, team_id) = 1", name="ck_task_grants_one_principal"
        ),
        sa.CheckConstraint("level IN ('read', 'write')", name="ck_task_grants_level"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_grants_task_id"), "task_grants", ["task_id"])
    op.create_index(op.f("ix_task_grants_user_id"), "task_grants", ["user_id"])
    op.create_index(op.f("ix_task_grants_team_id"), "task_grants", ["team_id"])
    op.create_index(
        "uq_task_grants_user",
        "task_grants",
        ["task_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_task_grants_team",
        "task_grants",
        ["task_id", "team_id"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL"),
    )

    op.create_table(
        "task_events",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _now("created_at"),
        sa.CheckConstraint(f"kind IN {EVENT_KINDS}", name="ck_task_events_kind"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        # SET NULL: deleting a person must not rewrite history.
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_events_task", "task_events", ["task_id", "id"])

    op.create_table(
        "notifications",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link_path", sa.String(length=500), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emailed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _now("created_at"),
        sa.CheckConstraint(f"kind IN {NOTIFICATION_KINDS}", name="ck_notifications_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user", "notifications", ["user_id", "created_at"])
    op.create_index(
        "ix_notifications_unread",
        "notifications",
        ["user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("task_events")
    op.drop_table("task_grants")
    op.drop_table("tasks")
