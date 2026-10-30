"""Record the actual time an unresolved discrepancy is detected."""
from alembic import op
import sqlalchemy as sa

revision = '0017_discrepancy_time'
down_revision = '0016_ml_training'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('discrepancies', sa.Column('detected_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('discrepancies', 'detected_at')
