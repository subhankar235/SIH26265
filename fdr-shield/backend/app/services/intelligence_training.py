"""Reproducible, provenance-aware training tools for review prioritization.

Synthetic rows are useful for pipeline checks only and can never be promoted to
operational inference. Production training requires independently labelled real
review outcomes supplied as a validated CSV.
"""
from __future__ import annotations

import csv
import json
import os
import random
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.intelligence_config import get_intelligence_settings
from app.services.intelligence_service import FEATURES, LABELS

CSV_FIELDS = (*FEATURES, 'label', 'origin')
MIN_ROWS_PER_CLASS = 20


def _validate_row(row: dict, line: int | str) -> dict:
    if row.get('origin') not in {'real', 'synthetic'}:
        raise ValueError(f'Invalid provenance on CSV line {line}.')
    if row.get('label') not in LABELS:
        raise ValueError(f'Unsupported review label on CSV line {line}.')
    clean = {'label': row['label'], 'origin': row['origin']}
    for feature in FEATURES:
        value = row.get(feature)
        if value in ('', None):
            clean[feature] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Invalid numeric feature {feature} on CSV line {line}.') from exc
        if not __import__('math').isfinite(number) or number < 0:
            raise ValueError(f'Invalid numeric feature {feature} on CSV line {line}.')
        if feature == 'amount' and number <= 0:
            raise ValueError(f'Amount must be positive on CSV line {line}.')
        if feature == 'tenure_days' and number <= 0:
            raise ValueError(f'Tenure must be positive on CSV line {line}.')
        if feature == 'missing_fields' and (number > 5 or not number.is_integer()):
            raise ValueError(f'Missing-field count is invalid on CSV line {line}.')
        if feature == 'discrepancy_count' and not number.is_integer():
            raise ValueError(f'Discrepancy count is invalid on CSV line {line}.')
        if feature == 'high_discrepancy_count' and not number.is_integer():
            raise ValueError(f'High-discrepancy count is invalid on CSV line {line}.')
        clean[feature] = number
    if (clean['high_discrepancy_count'] is not None and clean['discrepancy_count'] is not None
            and clean['high_discrepancy_count'] > clean['discrepancy_count']):
        raise ValueError(f'High-discrepancy count exceeds total on CSV line {line}.')
    if all(clean[feature] is None for feature in FEATURES):
        raise ValueError(f'All features are missing on CSV line {line}.')
    return clean


def generate_synthetic_rows(count: int = 1000, seed: int = 20261030) -> list[dict]:
    if isinstance(count, bool) or not isinstance(count, int) or not 100 <= count <= 100_000:
        raise ValueError('Synthetic pipeline dataset size must be between 100 and 100000 rows.')
    rng = random.Random(seed)
    rows = []
    for _ in range(count):
        label = 'additional_review' if rng.random() < .35 else 'routine'
        if label == 'additional_review':
            missing = rng.choices([0, 1, 2, 3], [0.1, .2, .4, .3])[0]
            discrepancies = rng.choices([0, 1, 2, 3], [.1, .25, .4, .25])[0]
            high = rng.randint(0, min(discrepancies, 2))
        else:
            missing = rng.choices([0, 1, 2], [.85, .13, .02])[0]
            discrepancies = rng.choices([0, 1], [.96, .04])[0]
            high = 0
        rows.append({'amount': round(rng.uniform(10_000, 5_000_000), 2),
                     'tenure_days': rng.randint(30, 3650), 'missing_fields': missing,
                     'discrepancy_count': discrepancies, 'high_discrepancy_count': high,
                     'label': label, 'origin': 'synthetic'})
    return rows


def read_training_csv(path: str | Path) -> list[dict]:
    settings = get_intelligence_settings()
    with open(path, newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if (reader.fieldnames is None or len(reader.fieldnames) != len(CSV_FIELDS)
                or set(reader.fieldnames) != set(CSV_FIELDS)):
            raise ValueError(f'Dataset columns must be exactly: {", ".join(CSV_FIELDS)}')
        rows = []
        for line, raw in enumerate(reader, start=2):
            if len(rows) >= settings.training_max_rows:
                raise ValueError('Dataset exceeds configured training row limit.')
            rows.append(_validate_row({**raw, **{key: value.strip() for key, value in raw.items()
                                                 if isinstance(value, str)}}, line))
    return rows


def validate_training_rows(rows: list[dict]) -> dict:
    if not isinstance(rows, list) or len(rows) > get_intelligence_settings().training_max_rows:
        raise ValueError('Dataset is missing or exceeds the configured row limit.')
    origins = {row.get('origin') for row in rows if isinstance(row, dict)}
    if len(origins) != 1 or not origins <= {'real', 'synthetic'}:
        raise ValueError('Dataset must have one consistent, explicit provenance.')
    clean = [_validate_row(row, index) for index, row in enumerate(rows, start=1)]
    fingerprints = {json.dumps([row.get(feature) for feature in FEATURES], sort_keys=True) for row in clean}
    if len(fingerprints) != len(clean):
        raise ValueError('Duplicate feature rows may leak across evaluation partitions.')
    labels = {label: sum(row['label'] == label for row in clean) for label in sorted(LABELS)}
    if any(count < MIN_ROWS_PER_CLASS for count in labels.values()):
        raise ValueError('Each review outcome requires at least 20 labelled examples.')
    return {'rows': clean, 'origin': next(iter(origins)), 'class_counts': labels,
            'dataset_sha256': __import__('hashlib').sha256(json.dumps(clean, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest()}


def train_and_evaluate(rows: list[dict], *, output_dir: str | Path | None = None,
                       random_seed: int = 20261030, dataset_reference: str | None = None) -> dict:
    validated = validate_training_rows(rows)
    rows = validated['rows']
    labels = [row['label'] for row in rows]

    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                                 precision_score, recall_score, roc_auc_score)
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    import joblib

    matrix = [[row.get(feature) for feature in FEATURES] for row in rows]
    x_train, x_test, y_train, y_test = train_test_split(
        matrix, labels, test_size=.25, random_state=random_seed, stratify=labels)
    model = Pipeline([('impute', SimpleImputer(strategy='median', add_indicator=True)),
                      ('scale', StandardScaler()),
                      ('classifier', LogisticRegression(class_weight='balanced', max_iter=1000,
                                                        random_state=random_seed))])
    model.fit(x_train, y_train)
    predicted = model.predict(x_test)
    positive = 'additional_review'
    probabilities = model.predict_proba(x_test)[:, list(model.classes_).index(positive)]
    metrics = {
        'test_rows': len(y_test), 'accuracy': float(accuracy_score(y_test, predicted)),
        'precision_additional_review': float(precision_score(y_test, predicted, pos_label=positive, zero_division=0)),
        'recall_additional_review': float(recall_score(y_test, predicted, pos_label=positive, zero_division=0)),
        'f1_additional_review': float(f1_score(y_test, predicted, pos_label=positive, zero_division=0)),
        'roc_auc': float(roc_auc_score([int(label == positive) for label in y_test], probabilities)),
        'confusion_matrix_labels': list(model.classes_),
        'confusion_matrix': confusion_matrix(y_test, predicted, labels=list(model.classes_)).tolist(),
        'acceptance_criteria': {'precision_min': .8, 'recall_min': .8},
    }
    meets = (metrics['precision_additional_review'] >= .8 and metrics['recall_additional_review'] >= .8)
    origin = validated['origin']
    if origin == 'real' and (not isinstance(dataset_reference, str) or not dataset_reference.strip()):
        raise ValueError('Real-data training requires an auditable dataset reference.')
    promotable = origin == 'real' and meets
    artifact_version = f'review-priority-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}-{uuid.uuid4().hex[:8]}'
    destination = Path(output_dir or get_intelligence_settings().artifact_path) / artifact_version
    destination.mkdir(parents=True, exist_ok=False)
    artifact_path = destination / 'review-priority.joblib'
    with tempfile.NamedTemporaryFile(dir=destination, suffix='.joblib.tmp', delete=False) as temp:
        temp_path = temp.name
    try:
        joblib.dump(model, temp_path)
        os.replace(temp_path, artifact_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    metadata = {'artifact_version': artifact_version, 'task': 'review_priority', 'origin': origin,
        'dataset_rows': len(rows), 'dataset_sha256': validated['dataset_sha256'],
        'class_counts': validated['class_counts'],
        'artifact_sha256': __import__('hashlib').sha256(artifact_path.read_bytes()).hexdigest(),
        'feature_names': list(FEATURES), 'dataset_reference': dataset_reference,
        'evaluation_metrics': metrics,
        'evaluation_passed': meets, 'deployment_status': 'candidate',
        'promotion_eligible': promotable, 'created_at': datetime.now(timezone.utc).isoformat(),
        'warning': 'Synthetic-origin evaluation is pipeline validation only; it is not operational evidence.'
            if origin == 'synthetic' else None}
    (destination / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return {'artifact_version': artifact_version, 'artifact_dir': str(destination),
            'origin': origin, 'metrics': metrics, 'evaluation_passed': meets,
            'promotion_eligible': promotable, 'deployment_status': 'candidate'}


def promote_artifact(artifact_dir: str | Path, active_dir: str | Path) -> dict:
    """Explicit operational promotion gate; synthetic artifacts are never eligible."""
    import shutil
    source = Path(artifact_dir)
    metadata_path = source / 'metadata.json'
    artifact_path = source / 'review-priority.joblib'
    if not metadata_path.is_file() or not artifact_path.is_file():
        raise ValueError('Candidate artifact is incomplete.')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    actual_artifact_hash = __import__('hashlib').sha256(artifact_path.read_bytes()).hexdigest()
    if metadata.get('artifact_sha256') != actual_artifact_hash:
        raise ValueError('Candidate artifact hash does not match its recorded metadata.')
    metrics = metadata.get('evaluation_metrics', {})
    if (metadata.get('origin') != 'real' or not metadata.get('promotion_eligible')
            or not metadata.get('evaluation_passed')
            or metrics.get('precision_additional_review', 0) < .8
            or metrics.get('recall_additional_review', 0) < .8):
        raise ValueError('Candidate does not meet real-data operational evaluation requirements.')
    target = Path(active_dir)
    target.mkdir(parents=True, exist_ok=True)
    previous_version = None
    try:
        previous_metadata = json.loads((target / 'metadata.json').read_text(encoding='utf-8'))
        previous_version = previous_metadata.get('artifact_version')
    except (OSError, ValueError, TypeError):
        pass
    temp_artifact = target / f'.{artifact_path.name}.tmp'
    shutil.copy2(artifact_path, temp_artifact)
    os.replace(temp_artifact, target / artifact_path.name)
    metadata['deployment_status'] = 'approved'
    metadata['promoted_at'] = datetime.now(timezone.utc).isoformat()
    metadata['rollback_reference'] = previous_version
    temp_metadata = target / '.metadata.json.tmp'
    temp_metadata.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    os.replace(temp_metadata, target / 'metadata.json')
    (source / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    if previous_version and previous_version != metadata['artifact_version']:
        previous_path = source.parent / previous_version / 'metadata.json'
        try:
            previous = json.loads(previous_path.read_text(encoding='utf-8'))
            previous['deployment_status'] = 'superseded'
            previous_path.write_text(json.dumps(previous, indent=2), encoding='utf-8')
        except (OSError, ValueError, TypeError):
            pass
    return {'artifact_version': metadata['artifact_version'], 'deployment_status': 'approved'}
