"""
database.py - Database Connection Setup

SQLAlchemy is an ORM (Object-Relational Mapper).
Instead of writing raw SQL, you work with Python objects.
Example: instead of "SELECT * FROM sources", you write Source.query.all()

This file sets up the connection pool and session factory.
"""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# The "engine" is the actual connection to PostgreSQL.
# pool_pre_ping=True means it tests the connection before using it
# (important if the DB restarted).
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,        # Max 10 simultaneous DB connections
    max_overflow=20,
)
logger.debug("Database engine created", extra={"event": "db_engine_created"})

# SessionLocal is a factory for database sessions.
# Each API request gets its own session (like a transaction context).
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# All database models inherit from this Base class.
# SQLAlchemy uses it to know which classes are DB tables.
class Base(DeclarativeBase):
    pass


def get_db():
    """
    FastAPI dependency - provides a DB session per request.
    
    The 'yield' makes this a context manager:
    - Code before yield: setup (open session)
    - Code after yield: cleanup (close session, even if error occurred)
    
    Usage in a route:
        @app.get("/something")
        def my_route(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
