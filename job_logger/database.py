"""Database engine and session helpers."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from job_logger.config import settings

POSTGRESQL_PLAIN_PREFIX = "postgresql://"
POSTGRESQL_SHORT_PREFIX = "postgres://"
POSTGRESQL_PSYCOPG_PREFIX = "postgresql+psycopg://"


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


# The engine is module-level so request handlers share one connection pool.
engine: Engine

# SessionLocal creates short-lived sessions for requests and tests.
SessionLocal: sessionmaker[Session]


def normalize_database_url(database_url: str) -> str:
    """Return a SQLAlchemy URL that uses the installed PostgreSQL driver."""

    normalized_database_url = database_url.strip()
    if normalized_database_url.startswith(POSTGRESQL_PLAIN_PREFIX):
        return normalized_database_url.replace(POSTGRESQL_PLAIN_PREFIX, POSTGRESQL_PSYCOPG_PREFIX, 1)
    if normalized_database_url.startswith(POSTGRESQL_SHORT_PREFIX):
        return normalized_database_url.replace(POSTGRESQL_SHORT_PREFIX, POSTGRESQL_PSYCOPG_PREFIX, 1)
    return normalized_database_url


def create_database_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine with safe defaults for the configured backend."""

    normalized_database_url = normalize_database_url(database_url)
    if normalized_database_url.startswith("sqlite"):
        return create_engine(
            normalized_database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )

    return create_engine(
        normalized_database_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
        future=True,
    )


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
