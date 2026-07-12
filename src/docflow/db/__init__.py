"""Knowledge Database module."""

from sqlmodel import create_engine, Session
from sqlalchemy.engine import Engine


# Engine cache to avoid creating multiple engines for the same database URL
_engines: dict[str, Engine] = {}


def get_engine(db_url: str) -> Engine:
    """Get or create a database engine.

    Args:
        db_url: Knowledge Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").

    Returns:
        SQLAlchemy database engine.
    """
    if db_url not in _engines:
        _engines[db_url] = create_engine(db_url)

    return _engines[db_url]


def get_session(db_url: str) -> Session:
    """Create a database session.

    Args:
        db_url: Knowledge Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").

    Returns:
        SQLAlchemy database session.
    """
    engine = get_engine(db_url)
    return Session(engine)
