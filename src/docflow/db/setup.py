"""Database setup module."""

from textwrap import dedent

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from docflow.db import get_engine

# Import all the data models to ensure that they are registered by SQLModel
from docflow.db.models import *


def create_functions(engine: Engine):
    """Create the database functions.

    Args:
        engine: SQLAlchemy database engine.
    """
    # Create a function to update the "updated_at" column on row updates
    with engine.begin() as conn:
        sql = dedent(
            """
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )

        conn.execute(text(sql))


def create_triggers(engine: Engine):
    """Create the database triggers.

    Args:
        engine: SQLAlchemy database engine.
    """
    # Create a trigger to update the "updated_at" column in the "documents" table
    # whenever a row is updated.
    with engine.begin() as conn:
        sql = dedent(
            """
            DROP TRIGGER IF EXISTS update_documents_updated_at ON documents;

            CREATE TRIGGER update_documents_updated_at
            BEFORE UPDATE ON documents
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
            """
        )

        conn.execute(text(sql))


def set_up(db_url: str):
    """Set up the database.

    This function creates the database tables if they don't exist.

    Args:
        db_url: Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").
    """
    engine = get_engine(db_url)

    # Create the database functions
    create_functions(engine)

    # Create the database tables of all the registered models
    SQLModel.metadata.create_all(engine)

    # Create the database triggers
    create_triggers(engine)
