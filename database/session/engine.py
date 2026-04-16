import os
from collections.abc import AsyncIterator
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# Antes de leer DATABASE_URL: .env no debe pisar variables ya fijadas (p. ej. run-real-scrape-supabase.ps1).
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://ota_user:ota_password@localhost:5432/ota_intel")


def get_asyncpg_connect_args() -> dict:
    """Compatibilidad con PgBouncer (Supabase pooler): ver dialecto asyncpg en SQLAlchemy."""
    u = os.getenv("DATABASE_URL", "") or DATABASE_URL
    if "postgresql+asyncpg" not in u:
        return {}
    # asyncpg: caché de sentencias preparadas a nivel driver.
    # SQLAlchemy asyncpg: caché del adaptador + nombres únicos (evita DuplicatePreparedStatement con pooler).
    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


async_engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=get_asyncpg_connect_args(),
)

session_factory = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
