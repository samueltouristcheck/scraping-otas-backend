"""Estado del scrape manual (botón en dashboard) para barra de progreso vía GET /scraping/status."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

_lock = asyncio.Lock()
_state: dict[str, Any] = {
    "status": "idle",
    "percent": 0,
    "phase": "",
    "detail": "",
    "error": None,
    "updated_at": None,
}


async def read_state() -> dict[str, Any]:
    async with _lock:
        return dict(_state)


async def try_set_running() -> bool:
    """Devuelve False si ya hay un job en curso."""
    async with _lock:
        if _state["status"] == "running":
            return False
        _state["status"] = "running"
        _state["percent"] = 0
        _state["phase"] = ""
        _state["detail"] = "Iniciando…"
        _state["error"] = None
        _state["updated_at"] = datetime.now(timezone.utc).isoformat()
        return True


async def mark_error(message: str) -> None:
    async with _lock:
        _state["status"] = "error"
        _state["error"] = message
        _state["detail"] = message
        _state["updated_at"] = datetime.now(timezone.utc).isoformat()


async def mark_done(detail: str = "Completado") -> None:
    async with _lock:
        _state["status"] = "done"
        _state["percent"] = 100
        _state["phase"] = ""
        _state["detail"] = detail
        _state["error"] = None
        _state["updated_at"] = datetime.now(timezone.utc).isoformat()


async def reset_idle() -> None:
    async with _lock:
        _state["status"] = "idle"
        _state["percent"] = 0
        _state["phase"] = ""
        _state["detail"] = ""
        _state["error"] = None
        _state["updated_at"] = datetime.now(timezone.utc).isoformat()


class ManualScrapeProgress:
    """Avance por horizonte scrapeado (GYG o Viator)."""

    def __init__(self, total_steps: int) -> None:
        self._total = max(1, total_steps)
        self._done = 0

    async def advance(self, phase: str, detail: str) -> None:
        self._done += 1
        pct = min(100, int(100 * self._done / self._total))
        async with _lock:
            _state["status"] = "running"
            _state["percent"] = pct
            _state["phase"] = phase
            _state["detail"] = detail
            _state["error"] = None
            _state["updated_at"] = datetime.now(timezone.utc).isoformat()
