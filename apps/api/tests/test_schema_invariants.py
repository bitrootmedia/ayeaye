"""Schema rules that a migration could quietly undo.

No database: these read the SQLAlchemy metadata, so they run in milliseconds
and catch the mistake at the point it's written rather than on deploy.
"""

from app.db.base import Base
from app.models import User


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
