"""Persist explicit workflow replay/reprocess provenance."""
from alembic import op
import sqlalchemy as sa

revision = '0007_workflow_replay_context'
down_revision = '0006_outbox_delivery_leases'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workflow_instances') as batch:
        batch.add_column(sa.Column('replay_document_id', sa.Integer(),
            sa.ForeignKey('documents.id', name='fk_workflow_replay_document'), nullable=True))
        batch.add_column(sa.Column('replay_from_execution_id', sa.Integer(),
            sa.ForeignKey('workflow_node_executions.id', name='fk_workflow_replay_execution'), nullable=True))
        batch.add_column(sa.Column('replay_requested_by', sa.Integer(),
            sa.ForeignKey('users.id', name='fk_workflow_replay_user'), nullable=True))
        batch.add_column(sa.Column('replay_reason', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('workflow_instances') as batch:
        batch.drop_column('replay_reason')
        batch.drop_column('replay_requested_by')
        batch.drop_column('replay_from_execution_id')
        batch.drop_column('replay_document_id')
