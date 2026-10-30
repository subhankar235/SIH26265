"""Add client idempotency to Command Center executions."""
from alembic import op
import sqlalchemy as sa
revision='0010_command_idempotency'
down_revision='0009_workflow_pause_state'
branch_labels=None
depends_on=None
def upgrade():
    with op.batch_alter_table('command_executions') as batch:
        batch.add_column(sa.Column('idempotency_key',sa.String(255),nullable=True))
        batch.create_unique_constraint('uq_command_idempotency',['idempotency_key'])
def downgrade():
    with op.batch_alter_table('command_executions') as batch:
        batch.drop_constraint('uq_command_idempotency',type_='unique')
        batch.drop_column('idempotency_key')
