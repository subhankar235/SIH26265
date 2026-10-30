# Phases 15–17: Testing, Deployment, MVP Verification

## Repository mapping

This repository is **FastAPI + React/Vite**, not Next.js. Services are `backend`, `worker`, `beat`, PostgreSQL, Redis, MinIO, Mailhog and the mock-bank service. Celery beat is configured as one instance; do not scale the beat service without adding leader election. Alembic is the migration system. The checked-in frontend has a Vitest test script but no lint script/linter configuration.

## Phase 0 decisions / open questions

| Topic | Repo decision / remaining owner decision |
|---|---|
| Business timezone | `RULES_DEFAULT_TZ=Asia/Kolkata`; date-boundary tests pin IST midnight. UTC remains the storage/logging convention. |
| Bank integrations | Demo mock-bank only. No real bank endpoint is configured or called. |
| OCR / LLM | Pluggable Ollama vision; deterministic validation and scoped tool authorization remain authoritative. LLM provider/model/key choices are deployment configuration. |
| Notification delivery semantics | Transactional outbox is at-least-once for enqueue. SMTP cannot guarantee exactly-once. An expired `sending` lease becomes `uncertain`/`dead`, with no blind resend. A human reconciles uncertain outcomes. |
| Malware scanning | Optional ClamAV INSTREAM. When configured, outage/malware fails closed. If absent, MIME, file-signature and size checks still run; AV coverage is not claimed. |
| ML | No trainer or ML dependency shipped. Gate 0 blocks unclassified legacy rows and synthetic rows. Eligibility only means data volume allows a training review. |
| Retention, offsite backup and encryption key ownership | **Policy-owner decision required** before production retention/export settings can be claimed. Backup helper does not prune or upload backups. |
| Production deployment | Compose values are explicitly development/demo values. Production requires operator-owned secrets, TLS/proxy setup, backup destination, monitoring and restore rehearsal. This repo does not assert regulatory compliance or production readiness. |

## Test coverage and verification status

Run from repository root unless noted:

```powershell
cd backend
python -m pytest -q
cd ..\frontend
npm test
npm run build
```

`npm run lint` is not configured; do not treat it as a passing check. Frontend acceptance instead uses Vitest and the production Vite build.

### Recorded run in this workspace

- `python -m pytest -q`: **79 passed, 1 skipped** (the live integration is opt-in); 2 existing python-jose `utcnow()` deprecation warnings.
- `npm test`: **7 passed**.
- `npm run build`: **passed**.
- `docker compose config --quiet`: **passed**.
- SQLite Alembic `upgrade head → downgrade -1 → upgrade head`: **passed** on a disposable DB. `0011` downgrade is additive, so ML provenance/audit chain remain present for compatibility.
- `git diff --check`: **passed** (only Git line-ending conversion notices).
- `docker compose up --build`: **not run** because Docker Desktop daemon was unavailable in this workspace.

Migration round-trip on an isolated disposable SQLite database (set a unique temporary `DATABASE_URL`):

```powershell
cd backend
$env:DATABASE_URL='sqlite+aiosqlite:///C:/path/to/disposable/phase-roundtrip.db'
python -m alembic upgrade head
python -m alembic downgrade -1
python -m alembic upgrade head
```

The current `0011` downgrade is deliberately compatibility/additive: it leaves ML provenance and audit-integrity objects in place and supplies defaults so an older application build can still insert audit records. It is not a destructive full rollback. Test on a disposable copy before applying to a data-bearing DB.

### Implemented automated checks

- Exhaustive allowed/disallowed workflow transition pairs and official-role gates.
- IST midnight boundary, leap-day maturity offsets and T-0 behavior.
- Submit/instance/event/outbox rollback atomicity.
- Synthetic/real Gate 0 separation and seeded synthetic counts.
- Seeded synthetic-data reproducibility; advisory output is deterministic and tenant scoped.
- Duplicate event/outbox enqueue, duplicate worker delivery while waiting, safe PURE replay, side-effect replay guard, and worker lease recovery.
- Exactly one correction notification on repeated mismatch worker processing.
- Correction upload creates a new document version, retains the old version and verification result, and resumes workflow.
- Provider outage retry then single accepted send; simulated worker process death after provider acceptance yields uncertain/dead and is not resent blindly.
- Release request/decision dimensions, audited human approval, approval idempotency and command authorization/cross-tenant rejection.
- Audit tamper detection and database UPDATE/DELETE rejection.
- OCR schema/injection/timeout handling, upload scanner fail-closed behavior when configured, rate-limit fallback, and dashboard synthetic-origin separation.

### Failure-injection cases that require infrastructure

The unit/integration suite simulates worker death at the provider boundary and expired workflow leases. The following require a live disposable stack and are **not implied passed** by in-memory tests:

| Injection | Manual/integration procedure | Evidence to capture |
|---|---|---|
| Worker killed after provider accepts | Instrument test SMTP/provider to accept then kill worker before DB status update; let lease expire; inspect notification attempt/outbox and provider mailbox. | Exactly one external delivery; outbox marked uncertain/dead; no automatic resend. |
| PostgreSQL deadlock/serialization failure | Two independent transactions lock/update shared rows in opposite order; capture retry behavior and audit/outbox atomicity. | One committed business mutation and one matching audit/outbox effect, or clean rollback/retry. |
| OCR/LLM timeout and malformed JSON | Mock Ollama transport with timeout, 429/5xx, malformed schema and prompt-injected document text. | Bounded retries; no fabricated fields; no tool execution; fallback state is deterministic. |
| Redis restart | Restart Redis while worker and API are active, enqueue work, restore Redis and observe pending/dead queues and fallback limits. | No silently lost outbox records; documented recovery timing. |
| Duplicate SSE delivery/reconnect | Reconnect with Last-Event-ID and publish duplicate dedupe key; compare event IDs and UI refresh count. | Durable event is stored once and client applies state idempotently. |
| Cross-institution API isolation | Run two institutions with adversarial FDR/workflow/document/notification IDs against every scoped endpoint. | Every foreign record returns 404/empty scoped result; zero payload leakage. |

## Acceptance targets (targets, not achieved claims)

| Target | Automated evidence now | Remaining evidence |
|---|---|---|
| 0 duplicate notifications under failure injection | Outbox dedupe + retry and “ambiguous send is not resent” tests pass. | Live provider crash-boundary test required. SMTP itself cannot prove exactly-once across all providers. |
| 0 cross-institution leaks | Assistant/command service scoping tests and institution-scoped deterministic recommendation test pass. | Full authenticated HTTP adversarial matrix across every endpoint remains to run. |
| Worker recovery <= lease + retry | Expired lease test verifies requeue behavior; workflow lease is 240 seconds, dispatcher cadence 10 seconds, recovery cadence 30 seconds. | Live worker-kill timing test required; retry backoff may exceed one lease. |
| 100% mutating endpoints audited | Service mutation code paths use audit recording in reviewed flows. | A systematic route/service audit-coverage test is still needed; no global guarantee is claimed. |
| 100% command tools authorize server-side | Allowlist, scope resolution, command role checks and cross-tenant tests exist. | Add a tool-by-tool authorization instrumentation test before claiming the target. |
| ML evaluation targets | Gate plans specify metrics/thresholds. | No model has trained; no precision, C-index, AUC, calibration or BOCPD performance result exists. |

## Phase 16 Compose runbook (development stack)

1. Back up any existing Postgres volume before upgrade. Compose now publishes its own DB at host port **5434** by default to avoid collisions with host Postgres services; containers use `postgres:5432` on the Compose network.
2. Start the stack: `docker compose up --build -d`; verify `docker compose ps` reports healthy Postgres, Redis, and MinIO.
3. Run `docker compose exec backend alembic upgrade head`.
4. For a fresh **development/demo** database only, run `docker compose exec backend python -m scripts.seed` and `docker compose exec backend python -m scripts.backfill_workflows`.
5. Smoke API (`/health`, `/docs`), institution submission/correction, official scrutiny/approval, admin outbox/health, assistant isolation and SSE polling fallback. Run backend tests + frontend Vitest/build.
6. Validate backup with `python scripts/postgres_backup.py backup <private-dump-path>` and restore-check only into a different disposable PostgreSQL database via `RESTORE_DATABASE_URL`.

`backend/.env.example` is not a production secret store. Supply production database credentials and unique JWT/MFA/storage secrets via a managed secret mechanism. Configure HTTPS, secure cookies, explicit CORS origins and a trusted proxy. Configure ClamAV if required. Configure monitoring for `/health`, queue depth/oldest age, outbox dead/pending counts, worker lease expiry, workflow duration, notification failures, OCR latency/errors, SSE connections, audit-chain validity and backup/restore results. Logs include request ID, route path, status and duration only; do not add bodies, cookies, prompts or document text.

### Progressive release / rollback

Deploy in order: backup → migrations → API → drain old workers → workers → single scheduler/beat → verify outbox and worker heartbeat → enable features in a staged environment. Current repo has no general feature-flag service; command/agent/workflow/ML paths are not claimed progressively flag-controlled. Gate ML remains deterministic and no model is active. Roll back by disabling ingress and stopping workers/beat before code rollback; migration `0011` is additive/compatibility-oriented and intentionally retains audit/ML data on downgrade. Restore a verified backup only under the data-owner incident process.

## Phase 17 MVP/demo scope

Repo MVP is implemented in the existing FastAPI/React stack: persist FDR/workflow/node/event/outbox/audit/approval data; extract with configured OCR; validate deterministically; route to correction or human scrutiny; inspect workflow events over SSE with polling fallback; retry/replay according to side-effect safeguards; confirm allowlisted commands. Correction, waiting-for-institution and human-review are represented as lifecycle/execution states and events; they are not currently three separate named graph executor nodes. The executor graph is `extract_document → validate_fields → route_case`.

The automated live integration remains opt-in via `FDR_INTEGRATION_URL`; real SMTP, live Ollama, Docker Compose lifecycle, notification-provider crash, and end-to-end human portal rehearsal are not asserted passed here. Demo script is in `README.md`; use a disposable demo DB and visibly label seeded FDRs as synthetic.

## Checklist snapshot (this workspace)

- [x] State, transition, date-boundary, tenant-scope, outbox, replay, correction-resume, audit-chain, synthetic separation and core OCR/fallback tests added/present.
- [x] SQLite migration upgrade tested; Phase 15 disposable upgrade → downgrade-one → upgrade-head round-trip recorded in session tooling.
- [x] Backend suite and frontend tests/build run; record actual terminal output in the release ticket.
- [ ] Live PostgreSQL Gate 0 counts: app DB credentials were rejected in the current environment. Do not infer counts from synthetic seeds.
- [ ] Live Compose/real provider, end-to-end portal rehearsal, Redis restart, PostgreSQL contention and backup restore rehearsal.
- [ ] Named policy owner decisions: retention duration, encrypted/offsite backup, uncertain-email reconciliation SLA and ML officer-review protocol.
- [ ] Phase 16 production deployment/rollback rehearsal and threat-model evidence review.
