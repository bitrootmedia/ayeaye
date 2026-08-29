"""disable/enable a member: a reversible suspension, not a removal

Revision ID: 0022_disable_members
Revises: 0021_login_events
Create Date: Phase 18

Adds `disabled` alongside `invited`/`active` on `organisation_members.status`.
`context_for` (services/organisations.py) only ever resolves an `active`
membership, so a disabled row simply stops matching it — every
organisation-scoped route 404s for that person from the next request on,
with no second check anywhere else to keep in sync. Unlike `remove_member`,
disabling never touches `projects.owner_user_id` or `tasks.owner_user_id`:
it is a pause, not a departure, so there is nothing to reassign.

`ck_org_members_active_has_user` widens the same way: a disabled row always
carries the `user_id` it had while active (only an active member can be
disabled), and the constraint says so explicitly rather than leaving it
merely true by construction.
"""

from alembic import op

revision = "0022_disable_members"
down_revision = "0021_login_events"
branch_labels = None
depends_on = None

OLD_STATUSES = "('invited', 'active')"
NEW_STATUSES = "('invited', 'active', 'disabled')"


def upgrade() -> None:
    op.drop_constraint("ck_org_members_status", "organisation_members", type_="check")
    op.create_check_constraint(
        "ck_org_members_status", "organisation_members", f"status IN {NEW_STATUSES}"
    )

    op.drop_constraint("ck_org_members_active_has_user", "organisation_members", type_="check")
    op.create_check_constraint(
        "ck_org_members_active_has_user",
        "organisation_members",
        "status NOT IN ('active', 'disabled') OR user_id IS NOT NULL",
    )


def downgrade() -> None:
    # A disabled row has nowhere to go in the narrower constraint. Re-enabling
    # is the non-destructive choice — the same reasoning `disable_member`
    # itself is built on, not a data loss the downgrade should be inventing.
    op.execute("UPDATE organisation_members SET status = 'active' WHERE status = 'disabled'")

    op.drop_constraint("ck_org_members_active_has_user", "organisation_members", type_="check")
    op.create_check_constraint(
        "ck_org_members_active_has_user",
        "organisation_members",
        "status <> 'active' OR user_id IS NOT NULL",
    )

    op.drop_constraint("ck_org_members_status", "organisation_members", type_="check")
    op.create_check_constraint(
        "ck_org_members_status", "organisation_members", f"status IN {OLD_STATUSES}"
    )
