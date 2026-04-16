from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from database.session.engine import get_async_session


async def db_session_dependency() -> AsyncIterator[AsyncSession]:
    async for session in get_async_session():
        yield session
