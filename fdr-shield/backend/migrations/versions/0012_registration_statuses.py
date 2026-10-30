"""Add explicit rejected and suspended account states."""
from alembic import op
import sqlalchemy as sa

revision = '0012_registration_statuses'
down_revision = '0011_ml_provenance_audit_chain'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('ck_users_status', type_='check')
        batch.create_check_constraint('ck_users_status',
            "status IN ('invited','pending_email_verify','pending_approval','active','locked','suspended','rejected','disabled')")


def downgrade():
    bind = op.get_bind()
    unsupported = bind.execute(sa.text(
        "SELECT count(*) FROM users WHERE status IN ('suspended','rejected')"
    )).scalar_one()
    if unsupported:
        raise RuntimeError('Cannot downgrade while suspended or rejected account records exist.')
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('ck_users_status', type_='check')
        batch.create_check_constraint('ck_users_status',
            "status IN ('invited','pending_email_verify','pending_approval','active','locked','disabled')")
