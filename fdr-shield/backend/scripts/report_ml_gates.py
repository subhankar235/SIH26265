"""Read-only Gate 0 volume report for the currently configured database."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, engine
from app.services.ml_service import assess_gates


async def main():
    try:
        async with SessionLocal() as session:
            report=await assess_gates(session)
        print(json.dumps(report,indent=2,default=str))
    except Exception as exc:
        # Database driver exceptions can embed DSNs; disclose only exception type.
        print(json.dumps({'available':False,'error_type':type(exc).__name__,
            'message':'Gate report unavailable; no training data was read or modified.'},indent=2))
        raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__=='__main__':
    asyncio.run(main())
