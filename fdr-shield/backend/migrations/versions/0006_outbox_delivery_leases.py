"""Add outbox delivery leases and recoverable in-flight notification status."""
from alembic import op
import sqlalchemy as sa

revision = '0006_outbox_delivery_leases'
down_revision = '0005_workflow_execution_schema'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('outbox_events') as batch:
        batch.drop_constraint('ck_outbox_status', type_='check')
        batch.create_check_constraint('ck_outbox_status', "status IN ('pending','processing','sent','failed','dead')")
        batch.add_column(sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.execute("UPDATE outbox_events SET status='dead' WHERE status='processing'")
    with op.batch_alter_table('outbox_events') as batch:
        batch.drop_column('locked_until')
        batch.drop_constraint('ck_outbox_status', type_='check')
        batch.create_check_constraint('ck_outbox_status', "status IN ('pending','sent','failed','dead')")
