"""Move existing public applicants into approval queues without email verification."""
from alembic import op
import sqlalchemy as sa

revision = '0014_disable_public_email_verification'
down_revision = '0013_super_admin_setup_phone'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "UPDATE users SET status = 'pending_approval' "
        "WHERE role IN ('institution', 'aicte_official') "
        "AND status = 'pending_email_verify'"
    ))


def downgrade():
    # Existing applications may already have been approved; do not revert account states.
    pass
