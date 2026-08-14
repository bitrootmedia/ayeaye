"""Teams, project groups, projects, and the grants that make them visible.

The shape of the hierarchy:

    organisation ──► teams ──► team_members
                 ├─► project_groups ──► projects
                 └────────────────────► projects ──► project_members
                                                       (user XOR team)

**A project is private to its owner until it is shared.** Not org-wide, not
group-wide. Everything anyone else can see comes from a `project_members` row
naming them or a team they're in, or from being an organisation admin. See
`services/access.py` for the four rules that follow from that.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Grant levels on a project. `owner` is never stored — it is what being the
# project's owner or an organisation admin resolves to. Storing it would create
# a second, disagreeing answer to "who owns this".
LEVEL_READ = "read"
LEVEL_WRITE = "write"
LEVEL_OWNER = "owner"
GRANT_LEVELS = (LEVEL_READ, LEVEL_WRITE)
LEVEL_RANK = {LEVEL_READ: 0, LEVEL_WRITE: 1, LEVEL_OWNER: 2}


class Team(Base):
    """A named set of people inside an organisation.

    Teams exist to be the target of a grant. Granting "Design" access to a
    project and then changing who is in Design is the difference between
    managing access once and managing it every time somebody joins.
    """

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("organisation_id", "name", name="uq_teams_org_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    members: Mapped[list["TeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_members"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # CASCADE: removing someone from the product removes them from its teams,
    # which is the only sane reading. Their grants go with them.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    team: Mapped[Team] = relationship(back_populates="members")


class ProjectGroup(Base):
    """A flat folder for projects inside an organisation.

    **Deliberately flat.** A `parent_id` you never use still complicates every
    query that touches projects, and nesting can be added later against a
    schema that has proven it needs it.

    A group is a label, **not** an access boundary — you cannot grant on one.
    Access flows org → project → task; the group is part of the path, not a
    place to hang permissions. Making it one would mean every visibility query
    walks another level for a feature nobody has asked for.
    """

    __tablename__ = "project_groups"
    __table_args__ = (
        UniqueConstraint("organisation_id", "name", name="uq_project_groups_org_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Project(Base):
    """A project. Private to its owner until shared."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SET NULL, not CASCADE: deleting a folder must not delete the work in it.
    project_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Whoever created it, unless ownership has been handed over. RESTRICT,
    # because a project with no owner is one nobody can administer — removing
    # that person has to reassign first. Same rule as tasks (PLAN.md §5).
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # There is no separate `status` column. Archived-or-not is the whole of a
    # project's status today, and a status that can disagree with its own
    # timestamp is a bug with two places to fix it.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    grants: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    """One grant of access to one project, to a person **or** a team.

    `CHECK (num_nonnulls(user_id, team_id) = 1)` is what makes "or" mean or —
    without it a row could name both and every query would have to decide which
    one wins.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(user_id, team_id) = 1", name="ck_project_members_one_principal"
        ),
        CheckConstraint(f"level IN {GRANT_LEVELS!r}", name="ck_project_members_level"),
        # One grant per principal per project. Partial, because the other
        # column is NULL on every row and NULLs don't collide.
        Index(
            "uq_project_members_user",
            "project_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_project_members_team",
            "project_id",
            "team_id",
            unique=True,
            postgresql_where=text("team_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )

    level: Mapped[str] = mapped_column(String(16), nullable=False, server_default=LEVEL_READ)

    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="grants")
