import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import context
from sqlalchemy import engine_from_config,pool
from sqlalchemy.engine import make_url
from app.core.database import Base
from app.core.config import get_settings
from app import models
config=context.config
database_url = make_url(get_settings().database_url)
if database_url.drivername == 'postgresql+asyncpg':
 query = dict(database_url.query)
 if 'ssl' in query:
  query['sslmode'] = query.pop('ssl')
 database_url = database_url.set(drivername='postgresql+psycopg2', query=query)
elif database_url.drivername == 'sqlite+aiosqlite':
 database_url = database_url.set(drivername='sqlite')
config.set_main_option('sqlalchemy.url',database_url.render_as_string(hide_password=False).replace('%','%%'))
target_metadata=Base.metadata
def run_migrations_offline():
 context.configure(url=config.get_main_option('sqlalchemy.url'),target_metadata=target_metadata,literal_binds=True,compare_type=True)
 with context.begin_transaction(): context.run_migrations()
def run_migrations_online():
 connectable=engine_from_config(config.get_section(config.config_ini_section),prefix='sqlalchemy.',poolclass=pool.NullPool)
 with connectable.connect() as connection:
  context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
  with context.begin_transaction(): context.run_migrations()
run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
