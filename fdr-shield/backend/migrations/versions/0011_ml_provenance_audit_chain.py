"""Add provenance-aware ML gate registry and tamper-evident audit chaining."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from alembic import op
import sqlalchemy as sa

revision = '0011_ml_provenance_audit_chain'
down_revision = '0010_command_idempotency'
branch_labels = None
depends_on = None
GENESIS = '0' * 64


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _hash(previous: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=_json_default)
    return hashlib.sha256((previous + body).encode('utf-8')).hexdigest()


def _drop_audit_triggers(bind):
    if bind.dialect.name == 'sqlite':
        op.execute('DROP TRIGGER IF EXISTS audit_logs_no_update')
        op.execute('DROP TRIGGER IF EXISTS audit_logs_no_delete')
    elif bind.dialect.name == 'postgresql':
        op.execute('DROP TRIGGER IF EXISTS audit_logs_no_update_delete ON audit_logs')


def _create_audit_triggers(bind):
    if bind.dialect.name == 'sqlite':
        op.execute("CREATE TRIGGER IF NOT EXISTS audit_logs_no_update BEFORE UPDATE ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END")
        op.execute("CREATE TRIGGER IF NOT EXISTS audit_logs_no_delete BEFORE DELETE ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END")
    elif bind.dialect.name == 'postgresql':
        op.execute("CREATE OR REPLACE FUNCTION reject_audit_log_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit_logs is append-only'; END; $$")
        op.execute("CREATE TRIGGER audit_logs_no_update_delete BEFORE UPDATE OR DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation()")


def _set_compatibility_hash_columns(*, nullable: bool, with_default: bool):
    bind=op.get_bind()
    default=sa.text("'"+GENESIS+"'") if with_default else None
    if bind.dialect.name=='sqlite':
        _drop_audit_triggers(bind)
        with op.batch_alter_table('audit_logs') as batch:
            for name in ('previous_hash','record_hash'):
                batch.alter_column(name,existing_type=sa.String(64),nullable=nullable,server_default=default)
        _create_audit_triggers(bind)
    else:
        for name in ('previous_hash','record_hash'):
            op.alter_column('audit_logs',name,existing_type=sa.String(64),nullable=nullable,server_default=default)


def _rechain_appended_legacy_rows(bind):
    """Re-link audit rows inserted by a rolled-back old app using DB defaults."""
    head=sa.table('audit_chain_heads',sa.column('id',sa.Integer),
        sa.column('latest_log_id',sa.Integer),sa.column('chain_hash',sa.String))
    current=bind.execute(sa.select(head).where(head.c.id==1)).mappings().first()
    if not current: return
    previous=current['chain_hash'];latest_id=current['latest_log_id'] or 0
    audit=sa.table('audit_logs',sa.column('id',sa.Integer),sa.column('user_id',sa.Integer),
        sa.column('actor_type',sa.String),sa.column('institution_id',sa.Integer),sa.column('request_id',sa.String),
        sa.column('entity',sa.String),sa.column('entity_id',sa.Integer),sa.column('action',sa.String),
        sa.column('ip_address',sa.String),sa.column('delta_changes',sa.JSON),sa.column('created_at',sa.DateTime),
        sa.column('previous_hash',sa.String),sa.column('record_hash',sa.String))
    rows=bind.execute(sa.select(audit).where(audit.c.id>latest_id).order_by(audit.c.id)).mappings()
    for row in rows:
        payload={key:row[key] for key in ('user_id','actor_type','institution_id','request_id','entity',
            'entity_id','action','ip_address','delta_changes','created_at')}
        digest=_hash(previous,payload)
        bind.execute(audit.update().where(audit.c.id==row['id']).values(previous_hash=previous,record_hash=digest))
        previous,latest_id=digest,row['id']
    bind.execute(head.update().where(head.c.id==1).values(latest_log_id=latest_id,chain_hash=previous))


def upgrade():
    bind = op.get_bind()
    # Down-migrations preserve additive tables. If upgrading after an old app ran,
    # re-chain only rows appended after the last known chain head.
    if sa.inspect(bind).has_table('audit_chain_heads') and sa.inspect(bind).has_table('ml_model_versions'):
        _drop_audit_triggers(bind)
        _rechain_appended_legacy_rows(bind)
        _set_compatibility_hash_columns(nullable=False,with_default=False)
        _create_audit_triggers(bind)
        return
    op.add_column('fdrs', sa.Column('is_synthetic', sa.Boolean(), nullable=True))
    op.create_index('ix_fdrs_is_synthetic', 'fdrs', ['is_synthetic'])
    op.add_column('audit_logs', sa.Column('previous_hash', sa.String(64), nullable=True))
    op.add_column('audit_logs', sa.Column('record_hash', sa.String(64), nullable=True))

    audit = sa.table('audit_logs',
        sa.column('id', sa.Integer), sa.column('user_id', sa.Integer),
        sa.column('actor_type', sa.String), sa.column('institution_id', sa.Integer),
        sa.column('request_id', sa.String), sa.column('entity', sa.String),
        sa.column('entity_id', sa.Integer), sa.column('action', sa.String),
        sa.column('ip_address', sa.String), sa.column('delta_changes', sa.JSON),
        sa.column('created_at', sa.DateTime), sa.column('previous_hash', sa.String),
        sa.column('record_hash', sa.String))
    previous = GENESIS
    latest_id = None
    for row in bind.execute(sa.select(audit).order_by(audit.c.id)).mappings():
        payload = {key: row[key] for key in ('user_id', 'actor_type', 'institution_id', 'request_id',
            'entity', 'entity_id', 'action', 'ip_address', 'delta_changes', 'created_at')}
        digest = _hash(previous, payload)
        bind.execute(audit.update().where(audit.c.id == row['id']).values(previous_hash=previous, record_hash=digest))
        previous, latest_id = digest, row['id']

    with op.batch_alter_table('audit_logs') as batch:
        batch.alter_column('previous_hash', existing_type=sa.String(64), nullable=False)
        batch.alter_column('record_hash', existing_type=sa.String(64), nullable=False)

    op.create_table('audit_chain_heads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('latest_log_id', sa.Integer(), nullable=True),
        sa.Column('chain_hash', sa.String(64), nullable=False))
    op.bulk_insert(sa.table('audit_chain_heads', sa.column('id', sa.Integer),
        sa.column('latest_log_id', sa.Integer), sa.column('chain_hash', sa.String)),
        [{'id': 1, 'latest_log_id': latest_id, 'chain_hash': previous}])
    op.create_index('ix_audit_logs_record_hash', 'audit_logs', ['record_hash'])
    _create_audit_triggers(bind)

    op.create_table('ml_model_versions',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('use_case', sa.String(32), nullable=False),
        sa.Column('version', sa.String(80), nullable=False), sa.Column('model_name', sa.String(100), nullable=False),
        sa.Column('status', sa.String(40), nullable=False), sa.Column('feature_version', sa.String(80), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=False), sa.Column('dataset_hash', sa.String(64), nullable=False),
        sa.Column('training_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('real_training_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('synthetic_training_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('evaluation_metrics', sa.JSON(), nullable=False), sa.Column('acceptance_criteria', sa.JSON(), nullable=False),
        sa.Column('library_versions', sa.JSON(), nullable=False),
        sa.Column('fallback_name', sa.String(100), nullable=False), sa.Column('is_synthetic', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('use_case', 'version', name='uq_ml_use_case_version'))
    op.create_index('ix_ml_model_use_case_created', 'ml_model_versions', ['use_case', 'created_at'])
    op.create_table('ml_demo_samples',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('batch_id', sa.String(36), nullable=False),
        sa.Column('use_case', sa.String(32), nullable=False), sa.Column('feature_version', sa.String(80), nullable=False),
        sa.Column('sample_index', sa.Integer(), nullable=False), sa.Column('features', sa.JSON(), nullable=False),
        sa.Column('is_synthetic', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_ml_demo_batch_id', 'ml_demo_samples', ['batch_id'])
    op.create_index('ix_ml_demo_usecase_created', 'ml_demo_samples', ['use_case', 'created_at'])
    op.create_table('ml_predictions',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('use_case', sa.String(32), nullable=False),
        sa.Column('entity_type', sa.String(32), nullable=False), sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('model_version_id', sa.Integer(), sa.ForeignKey('ml_model_versions.id'), nullable=True),
        sa.Column('dedupe_key', sa.String(64), nullable=True, unique=True),
        sa.Column('predictor', sa.String(100), nullable=False), sa.Column('score', sa.Float(), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=False), sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('is_synthetic', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_ml_prediction_case_created', 'ml_predictions', ['use_case', 'entity_id', 'created_at'])
    op.create_table('ml_operations_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metrics', sa.JSON(), nullable=False), sa.Column('is_synthetic', sa.Boolean(), nullable=True))
    op.create_index('ix_ml_ops_snapshot_captured', 'ml_operations_snapshots', ['captured_at'])


def downgrade():
    bind=op.get_bind()
    # Compatibility rollback is additive: retain audit integrity and ML data; give
    # old app versions DB defaults for the two new non-null audit columns. Never
    # delete predictions, provenance, audit hashes, or synthetic labels in rollback.
    _set_compatibility_hash_columns(nullable=False,with_default=True)
    _create_audit_triggers(bind)
