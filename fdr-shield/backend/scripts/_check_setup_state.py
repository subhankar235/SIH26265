import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import Settings

async def main():
    settings = Settings()
    engine = create_async_engine(settings.database_url, connect_args={'timeout': 8})
    try:
        async with engine.connect() as connection:
            count = (await connection.execute(text("select count(*) from users where role='admin'"))).scalar_one()
            print('Existing Super Admin accounts:', count)
            print('Setup secret configured:', bool(settings.super_admin_setup_secret))
    except Exception as exc:
        print('Setup state check failed:', type(exc).__name__)
    finally:
        await engine.dispose()

asyncio.run(main())
