from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Read-only ORM base -- these models mirror tables owned and written by
    the existing ingestion pipeline (db/schema.sql). This backend never
    creates/alters/drops them; see backend/README.md for the Alembic
    baselining procedure.
    """
