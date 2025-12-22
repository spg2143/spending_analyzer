# backend/db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

def _normalize_db_url(url: str) -> str:
    """
    Render/Neon/Supabase often give:
      postgres://...
      postgresql://...
    SQLAlchemy wants:
      postgresql+psycopg2://...
    """
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ENGINE = None
SessionLocal = None

Base = declarative_base()

def init_db():
    global ENGINE, SessionLocal
    if not DATABASE_URL:
        return False
    ENGINE = create_engine(
        _normalize_db_url(DATABASE_URL),
        pool_pre_ping=True,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ENGINE)
    return True

def get_db():
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
