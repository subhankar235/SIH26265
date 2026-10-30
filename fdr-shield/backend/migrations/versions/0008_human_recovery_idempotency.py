"""Persist retry inputs and idempotent human approval/recovery requests."""
from alembic import op
import sqlalchemy as sa

revision='0008_human_recovery_idempotency'
down_revision='0007_workflow_replay_context'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('workflow_instances') as batch:
        batch.add_column(sa.Column('retry_input_ref', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('retry_parent_execution_id', sa.Integer(),
            sa.ForeignKey('workflow_node_executions.id', name='fk_workflow_retry_parent'), nullable=True))
    with op.batch_alter_table('approval_records') as batch:
        batch.add_column(sa.Column('idempotency_key', sa.String(255), nullable=True))
        batch.create_unique_constraint('uq_approval_idempotency', ['idempotency_key'])

def downgrade():
    with op.batch_alter_table('approval_records') as batch:
        batch.drop_constraint('uq_approval_idempotency', type_='unique')
        batch.drop_column('idempotency_key')
    with op.batch_alter_table('workflow_instances') as batch:
        batch.drop_column('retry_parent_execution_id')
        batch.drop_column('retry_input_ref')
