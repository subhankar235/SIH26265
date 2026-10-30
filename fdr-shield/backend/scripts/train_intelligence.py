"""Train/evaluate a review-priority candidate from labelled CSV or test-only synthetic data."""
import argparse
import json

from app.services.intelligence_training import (
    generate_synthetic_rows, promote_artifact, read_training_csv, train_and_evaluate,
)
from app.core.intelligence_config import get_intelligence_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--dataset-csv', help='CSV containing validated labelled rows and origin=real')
    source.add_argument('--synthetic-rows', type=int, help='Generate synthetic rows for pipeline testing only')
    parser.add_argument('--seed', type=int, default=20261030)
    parser.add_argument('--dataset-reference', help='Auditable internal dataset identifier for real data')
    parser.add_argument('--promote', action='store_true', help='Promote eligible real-data candidate only')
    args = parser.parse_args()
    rows = read_training_csv(args.dataset_csv) if args.dataset_csv else generate_synthetic_rows(args.synthetic_rows, args.seed)
    result = train_and_evaluate(rows, random_seed=args.seed, dataset_reference=args.dataset_reference)
    if args.promote:
        result['promotion'] = promote_artifact(result['artifact_dir'],
                                               get_intelligence_settings().primary_artifact_path)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
