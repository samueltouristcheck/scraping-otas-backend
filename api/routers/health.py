from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import db_session_dependency
from core.config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="Liveness probe")
async def healthcheck() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "environment": settings.app_env}


@router.get("/db", summary="Database readiness probe")
async def database_healthcheck(
    session: AsyncSession = Depends(db_session_dependency),
) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
