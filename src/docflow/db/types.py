"""Data types module."""

from sqlalchemy.types import UserDefinedType

from docflow.config import settings


class Vector(UserDefinedType):
    """PostgreSQL vector type."""

    def __init__(self, precision: int = settings.embeddings_dimension):
        """Initialize the vector type.

        Args:
            precision: Vector type dimension.
        """
        self.precision = precision

    def get_col_spec(self, **kwargs):
        """Get the column specification.

        The column specification is the SQL string that defines the column in the
        database. The specification is used during the table creation through
        SQLAlchemy.
        """
        return f"vector({self.precision})"

    def bind_processor(self, dialect):
        """Return a function that converts a Python value to a database value.

        E.g. [1, 2, 3] (a list) would be converted to "[1, 2, 3]" (a string).
        """
        return lambda value: str(value) if value is not None else value

    def result_processor(self, dialect, coltype):
        """Return a function that converts a database value to a Python value.

        E.g. "[1, 2, 3]" (a string) would be converted to [1, 2, 3] (a list).
        """

        def get_value(value):
            # If "pgvector" returns None or a list of floats, pass it through
            if value is None or isinstance(value, list):
                return value

            # If "pgvector" returns a string, convert it to a list of floats
            return [float(i) for i in value.strip("[]").split(",")]

        return get_value
