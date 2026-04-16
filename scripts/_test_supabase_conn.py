"""One-off: python scripts/_test_supabase_conn.py (needs DATABASE_URL in env)."""
import asyncio
import os
import sys

import asyncpg


async def main() -> None:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("NO_DATABASE_URL", file=sys.stderr)
        sys.exit(1)
    dsn = raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        conn = await asyncpg.connect(dsn)
        v = await conn.fetchval("select 1")
        await conn.close()
        print("DB_OK", v)
    except Exception as e:
        print("DB_FAIL", type(e).__name__, e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
