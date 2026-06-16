"""Database engine and session helpers."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from job_logger.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


# The engine is module-level so request handlers share one connection pool.
engine: Engine

# SessionLocal creates short-lived sessions for requests and tests.
SessionLocal: sessionmaker[Session]


def create_database_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine with safe defaults for the configured backend."""

    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )

    return create_engine(database_url, pool_pre_ping=True, future=True)


def configure_database(database_url: str) -> None:
    """Configure the global engine and request session factory."""

    global engine, SessionLocal

    engine = create_database_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def get_database_session() -> Generator[Session, None, None]:
    """Yield a database session and always close it after the request."""

    database_session = SessionLocal()
    try:
        yield database_session
    finally:
        database_session.close()


configure_database(settings.database_url)

