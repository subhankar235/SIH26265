"""Create the original FDR-Shield schema (kept frozen for future migrations)."""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Older development launches created the original tables with metadata.create_all
    # before Alembic was stamped. Adopt that existing schema instead of recreating it.
    if sa.inspect(op.get_bind()).has_table('users'):
        return
    op.create_table('institutions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('aicte_id', sa.String(50), nullable=False, unique=True),
        sa.Column('name', sa.String(), nullable=False), sa.Column('state', sa.String(), nullable=False),
        sa.Column('head_name', sa.String(), nullable=False), sa.Column('contact_email', sa.String(), nullable=False),
        sa.Column('contact_phone', sa.String(), nullable=False), sa.Column('telegram_chat_id', sa.String(), nullable=True))
    op.create_table('users',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(), nullable=False), sa.Column('role', sa.String(), nullable=False),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=True),
        sa.Column('totp_secret', sa.String(), nullable=True), sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table('fdrs',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=False),
        sa.Column('fdr_number', sa.String(50), nullable=False), sa.Column('bank_name', sa.String(), nullable=False),
        sa.Column('branch', sa.String(), nullable=False), sa.Column('amount', sa.Numeric(14,2), nullable=False),
        sa.Column('issue_date', sa.Date(), nullable=False), sa.Column('maturity_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False), sa.Column('trust_badge', sa.String(), nullable=False),
        sa.Column('declared_data', sa.JSON(), nullable=False), sa.Column('ocr_data', sa.JSON(), nullable=True),
        sa.Column('bank_data', sa.JSON(), nullable=True), sa.Column('last_alert_stage', sa.String(), nullable=True),
        sa.Column('replaces_fdr_id', sa.Integer(), sa.ForeignKey('fdrs.id'), nullable=True))
    op.create_index('ix_fdrs_fdr_number', 'fdrs', ['fdr_number'])
    op.create_index('ix_fdrs_maturity_date', 'fdrs', ['maturity_date'])
    op.create_index('ix_fdrs_status', 'fdrs', ['status'])
    op.create_index('ix_fdrs_status_maturity', 'fdrs', ['status','maturity_date'])
    op.create_table('documents',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('fdr_id', sa.Integer(), sa.ForeignKey('fdrs.id'), nullable=False),
        sa.Column('doc_type', sa.String(), nullable=False), sa.Column('s3_key', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False), sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False))
    op.create_table('discrepancies',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('fdr_id', sa.Integer(), sa.ForeignKey('fdrs.id'), nullable=False),
        sa.Column('field', sa.String(), nullable=False), sa.Column('declared_value', sa.String(), nullable=False),
        sa.Column('extracted_value', sa.String(), nullable=False), sa.Column('source', sa.String(), nullable=False),
        sa.Column('severity', sa.String(), nullable=False), sa.Column('resolved', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('notifications',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('fdr_id', sa.Integer(), sa.ForeignKey('fdrs.id'), nullable=False),
        sa.Column('stage', sa.String(), nullable=False), sa.Column('channel', sa.String(), nullable=False),
        sa.Column('recipient', sa.String(), nullable=False), sa.Column('status', sa.String(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('fdr_id','stage','channel',name='uq_notification_fdr_stage_channel'))
    op.create_table('refund_requests',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('fdr_id', sa.Integer(), sa.ForeignKey('fdrs.id'), nullable=False),
        sa.Column('requested_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False), sa.Column('status', sa.String(), nullable=False),
        sa.Column('reviewed_by', sa.Integer(), nullable=True), sa.Column('remarks', sa.Text(), nullable=True))
    op.create_table('audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('entity', sa.String(), nullable=False), sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(), nullable=False), sa.Column('ip_address', sa.String(), nullable=False),
        sa.Column('delta_changes', sa.JSON(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_audit_entity_id', 'audit_logs', ['entity','entity_id'])


def downgrade():
    op.drop_table('audit_logs')
    op.drop_table('refund_requests')
    op.drop_table('notifications')
    op.drop_table('discrepancies')
    op.drop_table('documents')
    op.drop_index('ix_fdrs_status_maturity', table_name='fdrs')
    op.drop_index('ix_fdrs_status', table_name='fdrs')
    op.drop_index('ix_fdrs_maturity_date', table_name='fdrs')
    op.drop_index('ix_fdrs_fdr_number', table_name='fdrs')
    op.drop_table('fdrs')
    op.drop_table('users')
    op.drop_table('institutions')
