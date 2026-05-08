"""
database.py - Database Connection Setup

SQLAlchemy is the ORM (Object-Relational Mapper) used throughout the backend.
Instead of writing raw SQL, code works with Python objects:
- `db.query(Source).all()` runs SELECT * FROM sources
- `db.add(obj)` prepares an INSERT
- `db.commit()` flushes all pending changes to Postgres

This file sets up three shared objects used by every other module:
- `engine`: the actual TCP connection pool to PostgreSQL
- `SessionLocal`: a factory that creates per-request database sessions
- `Base`: the superclass all ORM model classes inherit from
"""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# The engine manages a pool of reusable TCP connections to Postgres.
# pool_pre_ping=True sends a cheap "SELECT 1" before handing out a connection —
# this detects stale connections that were dropped by the DB after idle timeout.
# pool_size=10: keep up to 10 connections open at all times.
# max_overflow=20: allow up to 20 additional connections under heavy load.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

logger.debug("Database engine created", extra={"event": "db_engine_created"})

# SessionLocal is a class (not an instance). Calling SessionLocal() creates a new
# database session — a unit of work that can read/write rows and be committed or
# rolled back as a single transaction.
# autocommit=False: changes are not saved until db.commit() is explicitly called.
# autoflush=False: pending changes are not sent to Postgres until commit/query forces it.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """
    Base class for all ORM models.

    Every table class in models.py inherits from this. SQLAlchemy uses it
    to discover all tables when Base.metadata.create_all() is called at startup.
    """
    pass


def get_db():
    """
    FastAPI dependency that provides a per-request database session.

    Used as a function parameter with FastAPI's Depends() mechanism:

        @app.get("/sources")
        def list_sources(db: Session = Depends(get_db)):
            return db.query(Source).all()

    The `yield` keyword makes this a context manager:
    - Code before yield: opens the session (setup)
    - Code after yield: closes the session (cleanup), even if an exception occurred

    Closing the session returns the underlying connection back to the pool.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
