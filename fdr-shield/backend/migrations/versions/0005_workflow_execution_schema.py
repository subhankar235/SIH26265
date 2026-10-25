"""Add node traces, checkpoints, approvals, recovery metadata and versioned documents."""
from alembic import op
import sqlalchemy as sa

revision = '0005_workflow_execution_schema'
down_revision = '0004_status_dimensions'
branch_labels = None
depends_on = None

LIFECYCLE = ('submitted','extraction_pending','extracting','validation_pending','validation_failed',
    'correction_required','awaiting_institution','ready_for_scrutiny','under_review',
    'awaiting_official_decision','accepted','renewal_required','renewed','release_requested',
    'awaiting_release_decision','release_approved','release_rejected','escalated','expired','completed')
EXECUTION = ('not_started','running','waiting_event','waiting_timer','waiting_human','paused',
    'retrying','failed','blocked','cancelled','completed')
AUTHORIZATION = ('not_required','pending','approved','rejected')


def _ensure_check(table, name, expression):
    insp = sa.inspect(op.get_bind())
    existing = {check.get('name') for check in insp.get_check_constraints(table)}
    if name not in existing:
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(name, expression)


def _ensure_index(table, name, columns, unique=False):
    existing = {index['name'] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    # Extend existing tables; preserve legacy columns and records.
    op.add_column('documents', sa.Column('version_no', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('documents', sa.Column('sha256', sa.String(64), nullable=True))
    op.add_column('documents', sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('supersedes_document_id', sa.Integer(),
            sa.ForeignKey('documents.id', name='fk_documents_supersedes_document'), nullable=True))
    _ensure_index('documents', 'ix_documents_fdr_type_version', ['fdr_id','doc_type','version_no'])

    op.add_column('discrepancies', sa.Column('rule_id', sa.String(100), nullable=True))
    op.add_column('discrepancies', sa.Column('rule_version', sa.String(80), nullable=True))

    op.add_column('audit_logs', sa.Column('actor_type', sa.String(16), nullable=False, server_default='user'))
    op.add_column('audit_logs', sa.Column('request_id', sa.String(64), nullable=True))
    with op.batch_alter_table('audit_logs') as batch:
        batch.add_column(sa.Column('institution_id', sa.Integer(),
            sa.ForeignKey('institutions.id', name='fk_audit_logs_institution'), nullable=True))
    op.execute("UPDATE audit_logs SET actor_type = 'system' WHERE user_id IS NULL")
    _ensure_index('audit_logs', 'ix_audit_logs_request_id', ['request_id'])
    _ensure_index('audit_logs', 'ix_audit_logs_institution_id', ['institution_id'])
    dialect = op.get_bind().dialect.name
    if dialect == 'sqlite':
        op.execute("CREATE TRIGGER IF NOT EXISTS trg_audit_no_update BEFORE UPDATE ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit_logs append-only'); END")
        op.execute("CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete BEFORE DELETE ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit_logs append-only'); END")
    elif dialect == 'postgresql':
        op.execute("CREATE OR REPLACE FUNCTION reject_audit_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'audit_logs append-only'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER trg_audit_no_update_delete BEFORE UPDATE OR DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()")

    # Workflow instances/events are created in 0004; add their constraints and polling indexes here.
    _ensure_check('fdrs','ck_fdr_lifecycle_state',
        "lifecycle_state IS NULL OR lifecycle_state IN (" + ','.join(repr(v) for v in LIFECYCLE) + ')')
    _ensure_check('fdrs','ck_fdr_execution_state',
        "execution_state IS NULL OR execution_state IN (" + ','.join(repr(v) for v in EXECUTION) + ')')
    _ensure_check('fdrs','ck_fdr_authorization_state',
        "authorization_state IS NULL OR authorization_state IN (" + ','.join(repr(v) for v in AUTHORIZATION) + ')')
    _ensure_check('workflow_instances','ck_workflow_lifecycle',
        "lifecycle_state IN (" + ','.join(repr(v) for v in LIFECYCLE) + ')')
    _ensure_check('workflow_instances','ck_workflow_execution',
        "execution_state IN (" + ','.join(repr(v) for v in EXECUTION) + ')')
    _ensure_check('workflow_instances','ck_workflow_authorization',
        "authorization_state IN (" + ','.join(repr(v) for v in AUTHORIZATION) + ')')
    _ensure_index('workflow_instances','ix_workflow_state_wake',['execution_state','next_wake_at'])
    with op.batch_alter_table('workflow_instances') as batch:
        existing_columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('workflow_instances')}
        if 'worker_lease_until' not in existing_columns:
            batch.add_column(sa.Column('worker_lease_until', sa.DateTime(timezone=True), nullable=True))
    _ensure_index('workflow_instances','ix_workflow_lease_until',['worker_lease_until'])
    _ensure_index('workflow_instances','ix_workflow_institution_lifecycle',['institution_id','lifecycle_state'])
    _ensure_index('workflow_events','ix_workflow_event_instance_received',['workflow_instance_id','received_at'])
    _ensure_index('workflow_instances','ix_workflow_instances_fdr_id',['fdr_id'])
    _ensure_index('workflow_instances','ix_workflow_instances_institution_id',['institution_id'])
    _ensure_check('outbox_events','ck_outbox_status',"status IN ('pending','sent','failed','dead')")
    _ensure_check('approval_records','ck_approval_decision',"decision IN ('approve','reject','request_correction','escalate')")
    _ensure_index('approval_records','ix_approval_instance_created',['workflow_instance_id','created_at'])

    # Correct any older status-only projection drafts without overwriting state
    # for a case that already has a persisted workflow instance.
    op.execute("""
    UPDATE fdrs SET
        lifecycle_state = CASE
            WHEN status = 'submitted' THEN 'submitted'
            WHEN status = 'under_scrutiny' THEN 'under_review'
            WHEN status = 'verified' THEN 'accepted'
            WHEN status = 'mismatch' THEN 'correction_required'
            WHEN status = 'renewal_requested' THEN 'renewal_required'
            WHEN status = 'expired' THEN 'expired'
            WHEN status = 'release_requested' THEN 'awaiting_release_decision'
            WHEN status = 'released' THEN 'release_approved'
            ELSE lifecycle_state
        END,
        execution_state = 'not_started',
        authorization_state = CASE
            WHEN status IN ('verified','released') THEN 'approved'
            WHEN status IN ('under_scrutiny','mismatch','renewal_requested','release_requested') THEN 'pending'
            ELSE 'not_required'
        END,
        verification_level = CASE WHEN ocr_data IS NOT NULL THEN 'extracted' ELSE 'declared' END
    WHERE NOT EXISTS (SELECT 1 FROM workflow_instances wi WHERE wi.fdr_id = fdrs.id)
    """)
    with op.batch_alter_table('approval_records') as batch:
        batch.add_column(sa.Column('source_audit_id', sa.Integer(),
            sa.ForeignKey('audit_logs.id', name='fk_approval_source_audit'), nullable=True))
    op.create_index('uq_approval_source_audit', 'approval_records', ['source_audit_id'], unique=True)

    op.create_table('verification_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('fdr_id', sa.Integer(), sa.ForeignKey('fdrs.id'), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('documents.id'), nullable=True),
        sa.Column('extraction_engine', sa.String(80), nullable=False),
        sa.Column('engine_version', sa.String(120), nullable=True),
        sa.Column('source', sa.String(40), nullable=False),
        sa.Column('verification_level', sa.String(24), nullable=False),
        sa.Column('idempotency_key', sa.String(255), nullable=True, unique=True),
        sa.Column('declared_snapshot', sa.JSON(), nullable=False),
        sa.Column('extracted_fields', sa.JSON(), nullable=True),
        sa.Column('bank_result', sa.JSON(), nullable=True),
        sa.Column('discrepancies', sa.JSON(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_verification_runs_fdr_created','verification_runs',['fdr_id','created_at'])

    op.create_table('workflow_node_executions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workflow_instance_id', sa.Integer(), sa.ForeignKey('workflow_instances.id'), nullable=False),
        sa.Column('node_key', sa.String(100), nullable=False), sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('parent_execution_id', sa.Integer(), sa.ForeignKey('workflow_node_executions.id'), nullable=True),
        sa.Column('replay_of_id', sa.Integer(), sa.ForeignKey('workflow_node_executions.id'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('input_ref', sa.JSON(), nullable=True), sa.Column('output_ref', sa.JSON(), nullable=True),
        sa.Column('input_hash', sa.String(64), nullable=True), sa.Column('error_class', sa.String(160), nullable=True),
        sa.Column('error_code', sa.String(80), nullable=True), sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('diagnostics', sa.JSON(), nullable=True), sa.Column('idempotency_key', sa.String(255), nullable=True, unique=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True), sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True), sa.Column('rule_version', sa.String(80), nullable=True),
        sa.Column('workflow_version', sa.String(80), nullable=False), sa.Column('triggered_by', sa.String(24), nullable=False, server_default='system'),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True), sa.Column('reason', sa.Text(), nullable=True),
        sa.UniqueConstraint('workflow_instance_id','node_key','attempt',name='uq_workflow_node_attempt'))
    _ensure_check('workflow_node_executions','ck_node_execution_status',
        "status IN ('pending','running','succeeded','failed','skipped','cancelled')")
    op.create_index('ix_node_execution_instance_started','workflow_node_executions',['workflow_instance_id','started_at'])
    op.create_index('ix_node_execution_status','workflow_node_executions',['status'])

    op.create_table('workflow_checkpoints',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workflow_instance_id', sa.Integer(), sa.ForeignKey('workflow_instances.id'), nullable=False),
        sa.Column('node_execution_id', sa.Integer(), sa.ForeignKey('workflow_node_executions.id'), nullable=True),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('state_snapshot', sa.JSON(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_checkpoint_instance_created','workflow_checkpoints',['workflow_instance_id','created_at'])

    op.create_table('exception_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workflow_instance_id', sa.Integer(), sa.ForeignKey('workflow_instances.id'), nullable=False),
        sa.Column('reason_code', sa.String(80), nullable=False), sa.Column('priority', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True), sa.Column('status', sa.String(16), nullable=False, server_default='open'),
        sa.Column('evidence_refs', sa.JSON(), nullable=False), sa.Column('recommended_action', sa.Text(), nullable=True),
        sa.Column('assigned_to', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    _ensure_check('exception_items','ck_exception_status',"status IN ('open','claimed','resolved')")
    op.create_index('ix_exception_status_due','exception_items',['status','due_at'])

    op.create_table('correction_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workflow_instance_id', sa.Integer(), sa.ForeignKey('workflow_instances.id'), nullable=False),
        sa.Column('fdr_id', sa.Integer(), sa.ForeignKey('fdrs.id'), nullable=False),
        sa.Column('requested_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False), sa.Column('required_fields', sa.JSON(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True), sa.Column('status', sa.String(16), nullable=False, server_default='open'),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    _ensure_check('correction_requests','ck_correction_status',"status IN ('open','submitted','accepted','rejected','expired')")
    op.create_index('ix_correction_status_due','correction_requests',['status','due_at'])

    op.create_table('automation_rules',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('rule_key', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=False, server_default=''), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('automation_rule_versions',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('rule_id', sa.Integer(), sa.ForeignKey('automation_rules.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('policy', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('rule_id','version',name='uq_rule_version'))

    op.create_table('command_executions',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('raw_command', sa.Text(), nullable=False), sa.Column('interpreted_plan', sa.JSON(), nullable=True),
        sa.Column('plan_hash', sa.String(64), nullable=True), sa.Column('authorization_result', sa.JSON(), nullable=True),
        sa.Column('requires_confirmation', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('confirmed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True), sa.Column('status', sa.String(16), nullable=False, server_default='planned'),
        sa.Column('steps', sa.JSON(), nullable=False), sa.Column('result_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    _ensure_check('command_executions','ck_command_status',"status IN ('planned','confirmed','running','succeeded','failed','cancelled')")
    op.create_index('ix_command_actor_created','command_executions',['user_id','created_at'])

    op.create_table('notification_delivery_attempts',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('notification_id', sa.Integer(), sa.ForeignKey('notifications.id'), nullable=False),
        sa.Column('attempt_no', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('idempotency_key', sa.String(255), nullable=True, unique=True), sa.Column('provider', sa.String(40), nullable=False),
        sa.Column('template_version', sa.String(80), nullable=True),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('provider_response', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True), sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('notification_id','attempt_no',name='uq_notification_attempt'))
    op.create_index('ix_notification_attempt_status','notification_delivery_attempts',['status'])


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == 'sqlite':
        op.execute('DROP TRIGGER IF EXISTS trg_audit_no_update')
        op.execute('DROP TRIGGER IF EXISTS trg_audit_no_delete')
    elif dialect == 'postgresql':
        op.execute('DROP TRIGGER IF EXISTS trg_audit_no_update_delete ON audit_logs')
        op.execute('DROP FUNCTION IF EXISTS reject_audit_mutation()')
    op.drop_table('notification_delivery_attempts')
    op.drop_index('ix_command_actor_created', table_name='command_executions')
    op.drop_table('command_executions')
    op.drop_table('automation_rule_versions')
    op.drop_table('automation_rules')
    op.drop_index('ix_correction_status_due', table_name='correction_requests')
    op.drop_table('correction_requests')
    op.drop_index('ix_exception_status_due', table_name='exception_items')
    op.drop_table('exception_items')
    op.drop_index('uq_approval_source_audit', table_name='approval_records')
    with op.batch_alter_table('approval_records') as batch:
        batch.drop_column('source_audit_id')
    op.drop_index('ix_approval_instance_created', table_name='approval_records')
    op.drop_index('ix_checkpoint_instance_created', table_name='workflow_checkpoints')
    op.drop_table('workflow_checkpoints')
    op.drop_index('ix_node_execution_status', table_name='workflow_node_executions')
    op.drop_index('ix_node_execution_instance_started', table_name='workflow_node_executions')
    op.drop_table('workflow_node_executions')
    op.drop_table('verification_runs')
    op.drop_index('ix_workflow_lease_until', table_name='workflow_instances')
    with op.batch_alter_table('workflow_instances') as batch:
        batch.drop_column('worker_lease_until')
    for table, check_name in (
        ('workflow_instances','ck_workflow_authorization'),
        ('workflow_instances','ck_workflow_execution'),
        ('workflow_instances','ck_workflow_lifecycle'),
        ('outbox_events','ck_outbox_status'),
        ('approval_records','ck_approval_decision'),
    ):
        existing = {check.get('name') for check in sa.inspect(op.get_bind()).get_check_constraints(table)}
        if check_name in existing:
            with op.batch_alter_table(table) as batch:
                batch.drop_constraint(check_name, type_='check')
    op.drop_index('ix_audit_logs_institution_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_request_id', table_name='audit_logs')
    with op.batch_alter_table('audit_logs') as batch:
        batch.drop_column('institution_id')
    op.drop_column('audit_logs', 'request_id')
    op.drop_column('audit_logs', 'actor_type')
    with op.batch_alter_table('documents') as batch:
        batch.drop_column('supersedes_document_id')
    op.drop_index('ix_documents_fdr_type_version', table_name='documents')
    op.drop_column('documents', 'uploaded_at')
    op.drop_column('documents', 'sha256')
    op.drop_column('documents', 'version_no')
    with op.batch_alter_table('discrepancies') as batch:
        batch.drop_column('rule_version')
        batch.drop_column('rule_id')
