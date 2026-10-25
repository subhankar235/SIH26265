"""Add account lifecycle and rotating cookie sessions to existing users."""
from alembic import op
import sqlalchemy as sa

revision = '0003_manual_auth'
down_revision = '0002_aicte_official_role'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('full_name', sa.String(255), nullable=False, server_default=''))
    op.add_column('users', sa.Column('status', sa.String(32), nullable=False, server_default='active'))
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('failed_login_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('session_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('mfa_secret_enc', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', name='fk_users_created_by_users'), nullable=True))
        batch.alter_column('password_hash', existing_type=sa.String(), nullable=True)
        batch.create_check_constraint('ck_users_role', "role IN ('institution','aicte_official','admin')")
        batch.create_check_constraint('ck_users_status', "status IN ('invited','pending_email_verify','pending_approval','active','locked','disabled')")
        batch.create_check_constraint('ck_users_role_institution',
            "(role = 'institution' AND institution_id IS NOT NULL) OR (role <> 'institution' AND institution_id IS NULL)")
    op.create_index('ix_users_role_status', 'users', ['role', 'status'])
    op.create_index('ix_users_status', 'users', ['status'])
    op.create_index('uq_users_email_lower', 'users', [sa.text('lower(email)')], unique=True)

    op.add_column('institutions', sa.Column('address', sa.String(500), nullable=True))
    op.add_column('institutions', sa.Column('status', sa.String(24), nullable=False, server_default='active'))
    op.add_column('institutions', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('institutions', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('family_id', sa.String(36), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ip_address', sa.String(100), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
    )
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'])
    op.create_index('ix_refresh_tokens_family_id', 'refresh_tokens', ['family_id'])
    op.create_index('ix_refresh_tokens_expires_at', 'refresh_tokens', ['expires_at'])

    op.create_table(
        'one_time_tokens',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('purpose', sa.String(32), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_one_time_tokens_user_id', 'one_time_tokens', ['user_id'])
    op.create_index('ix_one_time_tokens_purpose', 'one_time_tokens', ['purpose'])
    op.create_index('ix_one_time_tokens_token_hash', 'one_time_tokens', ['token_hash'])
    op.create_index('ix_one_time_tokens_expires_at', 'one_time_tokens', ['expires_at'])

    op.create_table(
        'login_attempts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email_attempted', sa.String(255), nullable=False),
        sa.Column('portal', sa.String(32), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('failure_reason', sa.String(64), nullable=True),
        sa.Column('ip_address', sa.String(100), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_login_attempts_email_attempted', 'login_attempts', ['email_attempted'])
    op.create_index('ix_login_attempt_email_time', 'login_attempts', ['email_attempted', 'created_at'])
    op.create_index('ix_login_attempt_ip_time', 'login_attempts', ['ip_address', 'created_at'])

    # Existing active demo/production accounts remain active; force legacy demo password change only by owner policy.


def downgrade():
    bind = op.get_bind()
    invited_without_password = bind.execute(sa.text("SELECT count(*) FROM users WHERE password_hash IS NULL")).scalar_one()
    if invited_without_password:
        raise RuntimeError('Cannot downgrade manual auth while invited/passwordless accounts exist; complete or remove invitations first.')
    op.drop_table('login_attempts')
    op.drop_table('one_time_tokens')
    op.drop_table('refresh_tokens')
    op.drop_column('institutions', 'updated_at')
    op.drop_column('institutions', 'created_at')
    op.drop_column('institutions', 'status')
    op.drop_column('institutions', 'address')
    op.drop_index('ix_users_status', table_name='users')
    op.drop_index('ix_users_role_status', table_name='users')
    op.drop_index('uq_users_email_lower', table_name='users')
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('ck_users_role_institution', type_='check')
        batch.drop_constraint('ck_users_status', type_='check')
        batch.drop_constraint('ck_users_role', type_='check')
        batch.alter_column('password_hash', existing_type=sa.String(), nullable=False)
        for column in ('updated_at', 'created_at', 'mfa_secret_enc', 'session_version', 'created_by', 'email_verified_at', 'last_login_at', 'locked_until',
                       'failed_login_count', 'must_change_password', 'status', 'full_name'):
            batch.drop_column(column)
