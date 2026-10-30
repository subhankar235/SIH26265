Run `alembic revision --autogenerate -m "init"` then `alembic upgrade head`.
env.py must import `app.models` (Base.metadata) and read DATABASE_URL from app.core.config.
