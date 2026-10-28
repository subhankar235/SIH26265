"""Persist isolated Command Center conversation identifiers."""
from alembic import op
import sqlalchemy as sa

revision='0015_cmd_conversation'
down_revision='0014_disable_email_verify'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('command_executions',sa.Column('conversation_id',sa.String(length=64),nullable=True))
    op.create_index('ix_command_executions_conversation_id','command_executions',['conversation_id'])


def downgrade():
    op.drop_index('ix_command_executions_conversation_id',table_name='command_executions')
    op.drop_column('command_executions','conversation_id')
