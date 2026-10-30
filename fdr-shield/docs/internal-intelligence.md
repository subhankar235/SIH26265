# Internal FDR review-priority pipeline

The `/admin/ml` page is an authorized administrative feature showcase. Internal
analysis is invoked, when explicitly enabled, from the persisted FDR workflow after the
existing deterministic field checks and mock-bank comparison. It creates an
advisory review-priority note only; it does not determine authenticity, bank
verification, case status, approval, rejection, or release.

The existing ML Governance route is an authorized admin feature showcase. Its
capability status endpoint reports only user-facing availability. The recent
findings table reuses `/verification/discrepancies?real_only=true`, which
returns explicitly real-origin findings with case references and server-side
pagination. The table does not imply an anomaly model is deployed. Existing
discrepancies predating migration `0017_discrepancy_time` have no recoverable
detection timestamp and are shown as `Not recorded`.

## Independent configuration

The backend reads `INTELLIGENCE_*` settings independently from the existing
`COMMAND_LLM_*` Command Center configuration and the OCR-only `OLLAMA_*`
configuration. The independent fallback URL, model, optional key, limits, and
enable switch are backend settings. Defaults leave this analysis disabled.
Never put provider credentials in the frontend or logs.

## Training and artifact workflow

Install optional dependencies from `backend/requirements-ml.txt`. The training
CSV must contain exactly `amount,tenure_days,missing_fields,discrepancy_count,
high_discrepancy_count,label,origin`. Labels are `routine` or
`additional_review`; origin is `real` or `synthetic`. Each dataset must have at
least 20 rows of each class and one consistent origin. Real-data runs require
an auditable `--dataset-reference`.

`python scripts/train_intelligence.py --synthetic-rows 1000` exercises actual
preprocessing, model fitting, held-out evaluation, and artifact writing. Such an
artifact is never eligible for promotion and its metrics are only pipeline
checks. For real labelled outcomes, use `--dataset-csv <private-csv> --dataset-reference
<internal-id>`. Real origin and provenance must be independently checked by the
operator; the tool cannot prove source legality or label correctness. Only a
real-data candidate meeting both configured precision and recall criteria can
be explicitly promoted with `--promote`. Promotion copies the model to the
configured active-artifact directory; the inference service additionally
requires approved metadata there.

Training candidates are staged under the configured private artifact path and
persisted in the existing private S3-compatible object bucket under the
`INTELLIGENCE_ARTIFACT_STORAGE_PREFIX` namespace. The active-artifact pointer is
written only after explicit promotion; workers synchronize and checksum the
approved artifact before inference. Training CSV uploads are temporary files
under the private staging directory and are removed when the task completes or
is recovered as stale. Training can also be queued with the existing Celery task
`app.workers.tasks_ml.train_review_priority`; Redis/Celery task status is the
job-status record. No model is operational until a qualified real dataset is
available, evaluation passes, and an operator promotes it.

## Fallback and failure behavior

When enabled, inference first attempts an approved artifact. Missing artifacts,
timeouts, load errors, or invalid categories trigger the separately configured
Ollama-compatible `/api/chat` fallback within bounded timeout/retry budgets.
The fallback schema and evidence indices are validated, and generated prose is
discarded in favor of a deterministic advisory sentence. If both paths fail,
the workflow records an `unavailable` assessment and continues its normal
official-review/correction process. No external model response changes
authoritative rules or official decisions.

The existing OCR Ollama integration and Command Center provider remain separate
and unchanged. Do not send documents, holder names, account identifiers, or raw
prompts to the analysis fallback; the integration supplies bounded numeric
features and discrepancy field/severity evidence only.
