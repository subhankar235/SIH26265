"""Persist workflow pause/resume origin state."""
from alembic import op
import sqlalchemy as sa

revision='0009_workflow_pause_state'
down_revision='0008_human_recovery_idempotency'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('workflow_instances') as batch:
        batch.add_column(sa.Column('paused_from_state',sa.String(32),nullable=True))

def downgrade():
    with op.batch_alter_table('workflow_instances') as batch:
        batch.drop_column('paused_from_state')
