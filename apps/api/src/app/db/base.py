from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base — every model inherits from this so they all
    land on one MetaData that Alembic autogenerate can see.

    Kept in its own module (no engine, no settings) so importing a model never
    drags in a database connection.
    """
