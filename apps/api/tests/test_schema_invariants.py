"""Schema rules that a migration could quietly undo.

No database: these read the SQLAlchemy metadata, so they run in milliseconds
and catch the mistake at the point it's written rather than on deploy.
"""

from pathlib import Path

from app.db.base import Base
from app.models import InstanceAdmin, Organisation, User
from app.services import access


def test_every_table_has_a_uuidv7_primary_key():
    """One convention, everywhere: a single server-generated UUIDv7 called
    `id`. Time-ordered so it indexes like a sequence, and it doesn't leak a row
    count the way a bigserial does. A model that forgets the server_default
    works fine in Python and then fails on any raw INSERT."""
    for table in Base.metadata.tables.values():
        pk = list(table.primary_key.columns)
        assert len(pk) == 1, f"{table.name} has a composite primary key"
        column = pk[0]
        assert column.name == "id", f"{table.name}'s primary key is {column.name}, not id"
        assert column.server_default is not None, f"{table.name}.id has no server default"
        assert "uuidv7()" in str(column.server_default.arg), (
            f"{table.name}.id is not defaulted from uuidv7()"
        )


def test_users_are_unique_on_both_identities():
    """Two rows for one person would silently split their memberships and
    tasks in half. The SuperTokens id is the join key; the email is how invites
    find someone before they have an account."""
    assert User.__table__.c.supertokens_user_id.unique
    assert User.__table__.c.email.unique


def test_a_user_has_no_role_or_kind_column():
    """Deliberate (PLAN.md §2.1): what a person may do comes from their
    organisation membership and grants, never from an attribute of the account.
    A `role` here would be a second place to look when something is denied."""
    columns = set(User.__table__.c.keys())
    assert not columns & {"role", "roles", "kind", "is_admin", "is_staff"}


def test_account_suspension_is_not_a_role():
    """`users.disabled_at` is allowed where `is_staff` is not, and the line
    between them is worth stating rather than rediscovering.

    A role says what someone may do *inside* an organisation, which is what
    membership and grants already answer — a second answer is the thing the
    test above exists to prevent. Suspension says whether the account works
    at all, upstream of the entire access model: the account-level twin of
    `organisation_members.status = 'disabled'`. If the account works,
    authorization is exactly what it was.

    The property that keeps that true is that `services/access.py` never
    reads it — asserted here rather than trusted, because a `disabled_at`
    that crept into a visibility expression would quietly be the staff tier
    this product doesn't have.
    """
    assert "disabled_at" in User.__table__.c.keys()

    source = (Path(access.__file__)).read_text()
    assert "disabled_at" not in source


def test_instance_admin_is_a_table_not_a_column():
    """Administering the *installation* is a row in its own table, never an
    attribute of the account.

    The test above forbids a `role`/`is_admin`/`is_staff` column on `users`
    because what somebody may do inside an organisation must come from their
    membership and their grants — one place to look. An instance admin
    doesn't answer that question at all: they get the operator view (counts,
    dates, names) and the ability to suspend an account or an organisation,
    and **no additional access inside any organisation whatsoever**.

    So it is allowed, on exactly the terms `disabled_at` is: the property
    that keeps it honest is that `services/access.py` never reads it. A
    visibility expression that knew about `instance_admins` would quietly be
    the staff tier this product doesn't have — a hidden task would stop being
    hidden, a private note would stop being private.
    """
    assert not set(User.__table__.c.keys()) & {"is_instance_admin", "instance_role"}

    source = Path(access.__file__).read_text()
    assert "instance_admin" not in source
    assert "InstanceAdmin" not in source
    # The model exists and points at an account, so the row is the whole fact.
    assert "user_id" in InstanceAdmin.__table__.c.keys()


def test_organisation_suspension_is_not_a_visibility_rule():
    """`organisations.suspended_at` is the organisation-level twin of
    `users.disabled_at`, and sits on the same side of the same line.

    It decides whether an organisation works at all; it says nothing about
    what anybody may do inside a working one. `services/organisations.py`'s
    `context_for` is the single enforcement point, upstream of every
    visibility expression — so `services/access.py` never reads it, and a
    `suspended_at` that crept into one would be a second, quieter answer to
    "can this person see this row".
    """
    assert "suspended_at" in Organisation.__table__.c.keys()

    source = Path(access.__file__).read_text()
    assert "suspended_at" not in source
