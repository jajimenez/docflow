"""Knowledge Database setup module."""

from sqlmodel import SQLModel

from docflow.db import get_engine

# Import all the data models to ensure that they are registered by SQLModel
import docflow.db.models  # noqa: F401


def set_up(db_url: str):
    """Set up the Knowledge Database.

    It creates the database tables if they don't exist.

    Args:
        db_url: Knowledge Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").
    """
    engine = get_engine(db_url)

    # Create the database tables of all the registered models
    SQLModel.metadata.create_all(engine)
