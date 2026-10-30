"""Data provenance, Gate 0 registry, and advisory prediction persistence."""
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MLModelVersion(Base):
    __tablename__ = 'ml_model_versions'
    __table_args__ = (UniqueConstraint('use_case', 'version', name='uq_ml_use_case_version'),
        Index('ix_ml_model_use_case_created', 'use_case', 'created_at'))
    id: Mapped[int] = mapped_column(primary_key=True)
    use_case: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(80), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    training_rows: Mapped[int] = mapped_column(Integer, default=0)
    real_training_rows: Mapped[int] = mapped_column(Integer, default=0)
    synthetic_training_rows: Mapped[int] = mapped_column(Integer, default=0)
    evaluation_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    acceptance_criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    library_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    fallback_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MLDemoSample(Base):
    __tablename__ = 'ml_demo_samples'
    __table_args__ = (Index('ix_ml_demo_usecase_created', 'use_case', 'created_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    use_case: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(80), nullable=False)
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MLPrediction(Base):
    __tablename__ = 'ml_predictions'
    __table_args__ = (Index('ix_ml_prediction_case_created', 'use_case', 'entity_id', 'created_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    use_case: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey('ml_model_versions.id'), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    predictor: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MLOperationsSnapshot(Base):
    __tablename__ = 'ml_operations_snapshots'
    __table_args__ = (Index('ix_ml_ops_snapshot_captured', 'captured_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_synthetic: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)


class MLTrainingJob(Base):
    __tablename__ = 'ml_training_jobs'
    __table_args__ = (Index('ix_ml_training_status_created', 'status', 'created_at'),
        Index('ix_ml_training_status_updated', 'status', 'updated_at'),
        UniqueConstraint('celery_task_id', name='uq_ml_training_celery_task'))
    id: Mapped[int] = mapped_column(primary_key=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='QUEUED')
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    dataset_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    class_counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evaluation_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
