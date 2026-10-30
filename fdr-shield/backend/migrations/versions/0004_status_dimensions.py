"""Add orthogonal status dimensions, backfill existing records, and create compatibility view.

Revision: 0004_status_dimensions
Revises: 0003_manual_auth
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_status_dimensions'
down_revision = '0003_manual_auth'
branch_labels = None
depends_on = None

LIFECYCLE_VALUES = ('submitted','extraction_pending','extracting','validation_pending','validation_failed',
    'correction_required','awaiting_institution','ready_for_scrutiny','under_review',
    'awaiting_official_decision','accepted','renewal_required','renewed','release_requested',
    'awaiting_release_decision','release_approved','release_rejected','escalated','expired','completed')


def _quote_statuses():
    return ','.join("'" + value + "'" for value in LIFECYCLE_VALUES)


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_cols = {col['name'] for col in insp.get_columns('fdrs')}

    # 1. Add orthogonal dimensions to fdrs if not already present
    with op.batch_alter_table('fdrs') as batch:
        if 'lifecycle_state' not in existing_cols:
            batch.add_column(sa.Column('lifecycle_state', sa.String(40), nullable=True))
        if 'execution_state' not in existing_cols:
            batch.add_column(sa.Column('execution_state', sa.String(24), nullable=True))
        if 'authorization_state' not in existing_cols:
            batch.add_column(sa.Column('authorization_state', sa.String(24), nullable=True))
        if 'verification_level' not in existing_cols:
            batch.add_column(sa.Column('verification_level', sa.String(24), nullable=True))

    # Create index on new status dimensions
    existing_indexes = {ix['name'] for ix in insp.get_indexes('fdrs')}
    if 'ix_fdrs_lifecycle_state' not in existing_indexes:
        op.create_index('ix_fdrs_lifecycle_state', 'fdrs', ['lifecycle_state'])
    if 'ix_fdrs_execution_state' not in existing_indexes:
        op.create_index('ix_fdrs_execution_state', 'fdrs', ['execution_state'])
    if 'ix_fdrs_authorization_state' not in existing_indexes:
        op.create_index('ix_fdrs_authorization_state', 'fdrs', ['authorization_state'])
    if 'ix_fdrs_verification_level' not in existing_indexes:
        op.create_index('ix_fdrs_verification_level', 'fdrs', ['verification_level'])
    if 'ix_fdrs_dimensions' not in existing_indexes:
        op.create_index('ix_fdrs_dimensions', 'fdrs', ['lifecycle_state', 'execution_state', 'authorization_state'])
    existing_checks = {check.get('name') for check in insp.get_check_constraints('fdrs')}
    with op.batch_alter_table('fdrs') as batch:
        constraints = (
            ('ck_fdr_lifecycle_state', f"lifecycle_state IS NULL OR lifecycle_state IN ({_quote_statuses()})"),
            ('ck_fdr_execution_state', "execution_state IS NULL OR execution_state IN ('not_started','running','waiting_event','waiting_timer','waiting_human','paused','retrying','failed','blocked','cancelled','completed')"),
            ('ck_fdr_authorization_state', "authorization_state IS NULL OR authorization_state IN ('not_required','pending','approved','rejected')"),
            ('ck_fdr_verification_level', "verification_level IS NULL OR verification_level IN ('declared','extracted','mock_verified','verified_external','ai_recommendation','human_scrutinized')"),
        )
        for name, expression in constraints:
            if name not in existing_checks:
                batch.create_check_constraint(name, expression)

    # 2. Backfill current business projections only; old data cannot prove that
    #    automation actually ran or that a mismatch was a human rejection.
    op.execute("""
    UPDATE fdrs SET
        lifecycle_state = COALESCE(lifecycle_state, CASE
            WHEN status = 'submitted' THEN 'submitted'
            WHEN status = 'under_scrutiny' THEN 'under_review'
            WHEN status = 'verified' THEN 'accepted'
            WHEN status = 'mismatch' THEN 'correction_required'
            WHEN status = 'renewal_requested' THEN 'renewal_required'
            WHEN status = 'expired' THEN 'expired'
            WHEN status = 'release_requested' THEN 'release_requested'
            WHEN status = 'released' THEN 'release_approved'
            ELSE 'submitted'
        END),
        execution_state = COALESCE(execution_state, 'not_started'),
        authorization_state = COALESCE(authorization_state, CASE
            WHEN status IN ('verified', 'released') THEN 'approved'
            WHEN status IN ('under_scrutiny', 'mismatch', 'renewal_requested', 'release_requested') THEN 'pending'
            ELSE 'not_required'
        END),
        verification_level = COALESCE(verification_level, CASE
            WHEN ocr_data IS NOT NULL THEN 'extracted'
            ELSE 'declared'
        END)
    WHERE lifecycle_state IS NULL OR execution_state IS NULL OR authorization_state IS NULL OR verification_level IS NULL
    """)

    # 3. Create compatibility view
    # Drops view if exists in Postgres/SQLite
    try:
        op.execute("DROP VIEW IF EXISTS v_fdrs_compatibility")
    except Exception:
        pass

    op.execute("""
    CREATE VIEW v_fdrs_compatibility AS
    SELECT
        id,
        institution_id,
        fdr_number,
        bank_name,
        branch,
        amount,
        issue_date,
        maturity_date,
        status,
        trust_badge,
        lifecycle_state,
        execution_state,
        authorization_state,
        verification_level,
        declared_data,
        ocr_data,
        bank_data,
        last_alert_stage,
        replaces_fdr_id
    FROM fdrs
    """)

    # 4. Create workflow & outbox tables if not existing
    if not insp.has_table('workflow_instances'):
        op.create_table(
            'workflow_instances',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('fdr_id', sa.Integer(), sa.ForeignKey('fdrs.id'), nullable=False),
            sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=False),
            sa.Column('workflow_version', sa.String(80), nullable=False, server_default='fdr-case-v1'),
            sa.Column('execution_version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('lifecycle_state', sa.String(40), nullable=False),
            sa.Column('execution_state', sa.String(32), nullable=False, server_default='not_started'),
            sa.Column('authorization_state', sa.String(24), nullable=False, server_default='not_required'),
            sa.Column('current_node', sa.String(100), nullable=True),
            sa.Column('paused_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('pause_reason', sa.Text(), nullable=True),
            sa.Column('next_wake_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.UniqueConstraint('fdr_id', 'execution_version', name='uq_workflow_fdr_execution_version'),
        )
        op.create_index('ix_workflow_instances_fdr_id', 'workflow_instances', ['fdr_id'])
        op.create_index('ix_workflow_instances_institution_id', 'workflow_instances', ['institution_id'])

    if not insp.has_table('workflow_events'):
        op.create_table(
            'workflow_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('workflow_instance_id', sa.Integer(), sa.ForeignKey('workflow_instances.id'), nullable=False),
            sa.Column('event_type', sa.String(80), nullable=False),
            sa.Column('payload', sa.JSON(), nullable=False),
            sa.Column('dedupe_key', sa.String(255), nullable=False, unique=True),
            sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_workflow_event_instance_received', 'workflow_events', ['workflow_instance_id', 'received_at'])

    if not insp.has_table('outbox_events'):
        op.create_table(
            'outbox_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('aggregate_id', sa.String(100), nullable=False),
            sa.Column('event_type', sa.String(80), nullable=False),
            sa.Column('payload', sa.JSON(), nullable=False),
            sa.Column('idempotency_key', sa.String(255), nullable=False, unique=True),
            sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_outbox_status_available', 'outbox_events', ['status', 'available_at'] if 'available_at' in [] else ['status', 'next_attempt_at'])

    if not insp.has_table('approval_records'):
        op.create_table(
            'approval_records',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('workflow_instance_id', sa.Integer(), sa.ForeignKey('workflow_instances.id'), nullable=False),
            sa.Column('fdr_id', sa.Integer(), sa.ForeignKey('fdrs.id'), nullable=False),
            sa.Column('refund_request_id', sa.Integer(), sa.ForeignKey('refund_requests.id'), nullable=True),
            sa.Column('request_type', sa.String(40), nullable=False),
            sa.Column('decision', sa.String(24), nullable=False),
            sa.Column('rationale', sa.Text(), nullable=False),
            sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('actor_role', sa.String(32), nullable=False),
            sa.Column('recommendation_ref', sa.String(100), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    try:
        op.execute("DROP VIEW IF EXISTS v_fdrs_compatibility")
    except Exception:
        pass

    insp = sa.inspect(op.get_bind())
    for tbl in ('approval_records', 'outbox_events', 'workflow_events', 'workflow_instances'):
        if insp.has_table(tbl):
            op.drop_table(tbl)

    insp = sa.inspect(op.get_bind())
    existing_checks = {check.get('name') for check in insp.get_check_constraints('fdrs')}
    with op.batch_alter_table('fdrs') as batch:
        for check_name in ('ck_fdr_verification_level','ck_fdr_authorization_state','ck_fdr_execution_state','ck_fdr_lifecycle_state'):
            if check_name in existing_checks:
                batch.drop_constraint(check_name, type_='check')
        existing_indexes = {ix['name'] for ix in insp.get_indexes('fdrs')}
        for index_name in ('ix_fdrs_dimensions','ix_fdrs_lifecycle_state','ix_fdrs_execution_state','ix_fdrs_authorization_state','ix_fdrs_verification_level'):
            if index_name in existing_indexes:
                batch.drop_index(index_name)
        for col in ('lifecycle_state', 'execution_state', 'authorization_state', 'verification_level'):
            if col in {c['name'] for c in insp.get_columns('fdrs')}:
                batch.drop_column(col)
