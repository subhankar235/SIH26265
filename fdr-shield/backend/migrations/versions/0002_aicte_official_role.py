"""Combine scrutiny officer and bureau chief roles."""
from alembic import op

revision = '0002_aicte_official_role'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE users SET role = 'aicte_official' WHERE role IN ('scrutiny_officer', 'bureau_chief')")


def downgrade():
    # The previous distinction cannot be reconstructed after roles are combined.
    op.execute("UPDATE users SET role = 'bureau_chief' WHERE role = 'aicte_official'")
