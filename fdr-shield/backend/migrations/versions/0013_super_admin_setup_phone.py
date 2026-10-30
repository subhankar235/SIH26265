"""Store initial Super Admin contact phone number."""
from alembic import op
import sqlalchemy as sa

revision = '0013_super_admin_setup_phone'
down_revision = '0012_registration_statuses'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('users')}
    if 'phone_number' not in columns:
        with op.batch_alter_table('users') as batch:
            batch.add_column(sa.Column('phone_number', sa.String(32), nullable=True))


def downgrade():
    # Preserve applicant contact data on downgrade; the nullable column is additive.
    pass
