"""Database connection and session management."""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.config import settings


# The engine manages the connection pool. Created once, reused.
engine = create_engine(
    settings.database_url,
    echo=False,  # Set True to see all SQL - useful for debugging
    pool_pre_ping=True,  # Verifies connections before using them
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """
    Yield a database session. Commits on success, rolls back on exception.

    Usage:
        with get_session() as session:
            session.add(some_object)
            # auto-commits when block exits cleanly
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
