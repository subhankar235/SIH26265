"""Index training-job status and update time for stale-job recovery."""
from alembic import op
import sqlalchemy as sa

revision = '0018_ml_training_recovery'
down_revision = '0017_discrepancy_time'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_index('ml_training_jobs', 'ix_ml_training_status_updated'):
        op.create_index('ix_ml_training_status_updated', 'ml_training_jobs', ['status', 'updated_at'])


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_index('ml_training_jobs', 'ix_ml_training_status_updated'):
        op.drop_index('ix_ml_training_status_updated', table_name='ml_training_jobs')
