"""Persist internal ML training job lifecycle and evaluation outcomes."""
from alembic import op
import sqlalchemy as sa

revision = '0016_ml_training'
down_revision = '0015_cmd_conversation'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ml_training_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('celery_task_id', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='QUEUED'),
        sa.Column('origin', sa.String(length=16), nullable=False),
        sa.Column('dataset_reference', sa.String(length=255), nullable=True),
        sa.Column('dataset_sha256', sa.String(length=64), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('class_counts', sa.JSON(), nullable=False),
        sa.Column('evaluation_metrics', sa.JSON(), nullable=False),
        sa.Column('artifact_version', sa.String(length=100), nullable=True),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('requested_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('celery_task_id', name='uq_ml_training_celery_task'))
    op.create_index('ix_ml_training_status_created', 'ml_training_jobs', ['status', 'created_at'])


def downgrade():
    op.drop_index('ix_ml_training_status_created', table_name='ml_training_jobs')
    op.drop_table('ml_training_jobs')
