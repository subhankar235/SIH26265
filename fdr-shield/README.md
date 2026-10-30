# NidhiTrack

AICTE security deposit and fixed deposit receipt (FDR) management demo. It uses FastAPI, async SQLAlchemy, PostgreSQL, Redis/Celery, MinIO, a React/Vite portal, optional Ollama Cloud OCR and a separately configurable LLM API for agents, plus a seeded demo bank gateway. The gateway is mock-only; no real bank systems are called. If a provider is unavailable or its key is absent, manual FDR entry and deterministic command/assistant/ML fallbacks remain available.

## Run with Docker Compose

Requirements: Docker Engine with the Compose plugin.

```powershell
docker compose up --build -d
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed
docker compose exec backend python -m scripts.backfill_workflows
docker compose exec backend python -m scripts.demo_flow
```

Open the frontend at http://localhost:5173, API docs at http://localhost:8000/docs, MinIO console at http://localhost:9001, Mailhog at http://localhost:8025, and the mock bank docs at http://localhost:9100/docs. Compose exposes its PostgreSQL service on host port 5434 by default (`POSTGRES_HOST_PORT` overrides it) to avoid colliding with a host database. Containers connect over Compose DNS at `postgres:5432`. The development seed includes synthetic demo data/accounts; production bootstrapping must use the one-time Admin CLI and account invitations.

The checked-in `backend/.env.example` contains development-only Compose values and no API keys. Set a random `JWT_SECRET` (at least 32 characters) in ignored `backend/.env` before starting the API; for example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. The default session lifetimes are `ACCESS_TOKEN_MINUTES=720` and `REFRESH_TOKEN_DAYS=30`. Refresh sessions are stored and rotated in the database; Redis is the broker/cache/rate-limit service, not the authentication session store. `OLLAMA_API_KEY` is only for Ollama OCR. The agent LLM has its own `COMMAND_LLM_API_URL`, `COMMAND_LLM_MODEL`, and `COMMAND_LLM_API_KEY`; it is disabled until you select/configure an LLM provider. Compose loads ignored `backend/.env` values as overrides. `S3_ENDPOINT` is the container-to-container storage address (`http://minio:9000`); `S3_PUBLIC_ENDPOINT` is used only to sign browser-readable links (`http://localhost:9000` in local Compose). Set the latter to the browser-reachable MinIO URL in other deployments. Never put keys in frontend variables or commit them. Demo seeding is blocked outside dev/test. For a non-demo database, migrate first, configure unique secrets, then run `python -m scripts.create_admin` once with `INITIAL_ADMIN_EMAIL` and `INITIAL_ADMIN_PASSWORD`; remove that password from the environment afterward. Production requires `APP_ENV=prod`, `COOKIE_SECURE=true`, a valid `MFA_ENCRYPTION_KEY`, `FRONTEND_ORIGIN`, and matching `CORS_ORIGINS` behind HTTPS. The bootstrap Admin must change the initial password.

After migrating an existing database, run the idempotent `backfill_workflows` script before relying on the new status projections. It imports a current-state snapshot only; legacy node-level run history cannot be reconstructed. New submissions enter a PostgreSQL-backed workflow via a transactional outbox; Celery executes extraction, validation and routing nodes, records checkpoints/errors, retries transient failures, waits for corrections/official review, and reclaims expired worker leases. Reminder/correction email delivery uses the outbox; ambiguous SMTP sends after a dispatcher crash are marked uncertain/dead rather than blindly resent. Workflow inspection/replay, SSE, Command Center, scoped assistance/operations agents and role-based screens are implemented in the current React app.

### Neon Object Storage for uploaded documents

The backend's S3-compatible adapter supports Neon Object Storage for FDR scans. In Neon, enable Object Storage for the target branch, create a **private** bucket, and create a credential with `storage:read` and `storage:write` scopes. Configure these backend-only environment variables on the API service:

```text
STORAGE_BACKEND=s3
S3_ENDPOINT=<branch S3 endpoint from Neon Storage connect details>
S3_REGION=<region from Neon Storage connect details>
S3_ACCESS_KEY=<Neon token_id / S3 access key ID>
S3_SECRET_KEY=<Neon s3_secret_access_key>
S3_BUCKET=<private bucket name>
S3_PUBLIC_ENDPOINT=
```

The endpoint and region are branch-specific. Leave `S3_PUBLIC_ENDPOINT` empty so short-lived signed document links use the same Neon endpoint. Never make FDR documents public or expose these credentials in frontend variables. Set the values in the backend host's secret environment configuration (for example, Render), not in committed files. The app uses path-style S3 requests and does not create public access; it checks the configured bucket at startup and attempts to create it if missing. Neon Object Storage and PostgreSQL are separate services, even when both belong to the same Neon project. See [Neon Object Storage setup](https://neon.com/docs/storage/get-started) and [S3 compatibility](https://neon.com/docs/storage/s3-compatibility).

## Verification, ML gates, and operations runbook

See [`docs/phase15-17-verification.md`](docs/phase15-17-verification.md) for test coverage, injection procedures, deployment/rollback steps, acceptance target status and the Phase 17 demo scope. Current local checks are `python -m pytest -q` from `backend`, plus `npm test` and `npm run build` from `frontend`. There is no configured frontend lint script. ML Gate 0 is available from Admin → ML governance / `/admin/ml`; models are not trained until real historical data volume and review criteria qualify. Seeded rows and generated examples are marked synthetic and excluded from real aggregate metrics.

To run a read-only authenticated concurrency check against a running API, set `LOAD_TEST_EMAIL` and `LOAD_TEST_PASSWORD` in the backend shell and run `python -m scripts.load_test_api`. Defaults are 100 concurrent readers and 5 rounds; set `LOAD_TEST_USERS` / `LOAD_TEST_ROUNDS` to adjust. It reports per-route p50/p95/p99 latency and errors without printing credentials or mutating records.

### Optional LLM agents

The agent LLM is disabled by default. To enable it, set `COMMAND_LLM_ENABLED=true` and configure the chosen provider’s `COMMAND_LLM_API_URL`, `COMMAND_LLM_MODEL`, and (if required) `COMMAND_LLM_API_KEY`. These are separate from Ollama OCR settings. Keep credentials out of frontend `VITE_*` variables. Ollama Cloud does not support structured outputs, so command intent JSON is requested in the prompt and then strictly validated server-side against the allowlist. For supported read-only FDR requests, the backend queries authorized records first and passes the bounded result to the LLM for a grounded answer; up to 200 maturity matches are returned per query, with larger totals counted and clearly marked as capped. If a provider is missing, unavailable, times out, or returns invalid output, the UI labels the deterministic, database-grounded response as a fallback. Mutating actions are server-authorized and follow each tool's confirmation policy.

Command Center access is available in all three portals. Institution users receive read-only queries scoped to their authenticated institution; AICTE Officials receive authorized read and workflow tools; Super Admin is read-only and does not receive financial approval or release authority through Command Center. Registered read tools cover total counts, latest FDR records, maturity searches, combined maturity/discrepancy analysis, workflow-state lists, FDR details/status, authorized task-status lookup, and failed-notification summaries. "Latest" records are ordered by descending database record ID because FDR rows do not store a creation timestamp. Registered official operations cover document rechecks, failed-node retries, workflow pause/resume, reminder drafts, and escalation. Case approval/rejection, release decisions, arbitrary administration, and free-form SQL are not Command Center tools.

Authentication uses separate Institution, AICTE Official, and Super Admin sign-in entry points backed by one shared role-derived SSO session. Existing `admin` role rows remain the stored Super Admin role for compatibility. Institution and AICTE Official applicants self-register and enter the appropriate approval queue immediately; email verification is temporarily disabled. Run `python -m alembic upgrade head` to move previously registered public applicants from `pending_email_verify` into the approval queue. Approved applicants can sign in with the password they set during registration. AICTE Officials decide Institution applications; Super Admins decide AICTE Official applications and may also decide Institution applications. The first Super Admin can be created at `/super-admin/setup` only when `SUPER_ADMIN_SETUP_SECRET` is configured in `backend/.env`; setup closes permanently once an Admin/Super Admin row exists. For local Compose, set a unique random value in the ignored `backend/.env`, recreate the backend with `docker compose up -d backend`, and enter that same value in the setup form. Remove the secret from the environment after setup. This page uses the same database lock as `python -m scripts.create_admin`; it cannot create additional Super Admins. Never put the setup secret in frontend environment variables. Access/rotating refresh tokens are HttpOnly cookies, browser state stores only the user profile, and unsafe cookie-authenticated requests use signed double-submit CSRF. Access-token refresh is single-flight across requests and uses the browser lock across tabs; temporary refresh-service failures do not clear the frontend session. Keep using one host consistently (for example, `localhost`, not a mix of `localhost` and `127.0.0.1`) so browser cookies remain in the same host scope. Admin-created accounts receive one-time invites. Local Compose invite/reset links appear in Mailhog.

Portal login includes the selected portal and the backend checks it against the stored account role before issuing a session. Cross-portal credentials are rejected with a generic authentication error; role fields supplied by clients are ignored. Existing sessions use shared role-derived SSO cookies, while protected APIs enforce their own role requirements.

The Official portal includes a persisted workflow control room, exception inbox, SSE progress, and a natural-language Command Center. General conversation uses the configured LLM and is persisted as same-user conversation turns. Follow-up context is bounded and used only for interpretation/reference resolution; case facts are always re-read through scoped server tools. Registered read tools cover FDR counts, recent records, maturity search, discrepancy listing/analysis, workflow and task status, and FDR details. Responses do not prove authenticity or constitute real-bank verification. Operational requests are interpreted into a typed allowlist; the LLM cannot choose arbitrary services, SQL, or permissions. Commands resolve case references on the server, show a plan, require confirmation for mutating operations, and persist status/results in `command_executions`; workers handle queued commands, while explicit local eager mode executes inline. Case approval and release decisions remain outside the Command Center. SQL is used for structured FDR data; vector/RAG search is not used. Existing deployments should run `python -m alembic upgrade head` to add the conversation identifier column before using persisted conversations.

The Control Room uses React Flow (`@xyflow/react`) to visualize the immutable backend `fdr-case-v1` graph: `extract_document → validate_fields → route_case`. Correction-required and official-review destinations are business outcomes, not executable nodes. Node status, errors, attempts, checkpoints, and events come from persisted execution records. Retry, extraction-checkpoint replay, pause, and resume call existing authorized backend operations. The graph is intentionally read-only: the repository has no workflow-definition editing or publishing service, so the interface does not expose pretend Save Draft or Publish actions. Pause is available only when the backend reports an idle worker lease. Eager local mode runs inline; asynchronous deployments require the configured Celery worker, beat scheduler, and Redis broker.

### Optional OCR

Compose sets `OCR_ENGINE=ollama_vision`, `OLLAMA_BASE_URL=https://ollama.com`, and `OLLAMA_MODEL=gemma4:31b`. Set `OLLAMA_API_KEY` in `backend/.env` for OCR only. With `OCR_FORMAT_CHECK=true`, Ollama also provides a bank-neutral FDR-like document-format screen, displayed as an advisory in preview and official review; it does not authenticate the document or verify the deposit with a bank. Offline EasyOCR/Tesseract modes extract fields but do not perform that visual format screen. If the provider is unavailable or misconfigured, the preview reports an error and fields can still be entered manually; the record remains unverified.

## Demo accounts

`python -m scripts.seed` creates the following development-only demo users. Password for each is `DemoPass123!`.

| Role | Email |
|---|---|
| Institution 1 | `institution1@example.test` |
| Institution 2–5 | `institution2@example.test` through `institution5@example.test` |
| AICTE Official | `officer@example.test` or `chief@example.test` |
| Admin | `admin@example.test` |

## Four-step demo

1. Sign in with `institution1@example.test` and upload a scan. Seed creates 15 sample records and copies genuine SBI, HDFC and PNB reference scans into `backend/sample_scans` with matching printed demo values. Generated text-only images remain labeled under `backend/tests/fixtures/negative_samples/`.
2. Upload a scan; when Ollama Cloud is configured OCR extracts fields, otherwise enter/review fields manually. Verification compares declared values against the mock bank and updates the trust badge.
3. Sign in as `officer@example.test`, inspect the SplitViewer and approve/reject; use `admin@example.test` to fire `POST /api/v1/notifications/test?fdr_id=<id>&stage=T-90` and check Mailhog at http://localhost:8025.
4. Use a matured, verified FDR to request a refund, then sign in as either AICTE Official account to approve/reject. Audit entries are visible in the Bureau portal.

## No-Docker Windows demo

Install Python 3.11+ and Node.js 20+. PostgreSQL/Redis are optional for the demo (SQLite + Celery eager mode are supported). Ollama Cloud is optional for OCR; the separate agent LLM provider is also optional. From `backend`, create a virtual environment and install `requirements.txt`. Set these environment variables in the backend PowerShell session:

```powershell
$env:DATABASE_URL='sqlite+aiosqlite:///./fdrshield.db'
$env:STORAGE_BACKEND='local'
$env:STORAGE_LOCAL_PATH='./var/fdr-documents'
$env:CELERY_TASK_ALWAYS_EAGER='true'
$env:MOCK_BANK_URL='http://127.0.0.1:9100'
$env:SMTP_HOST='127.0.0.1'
```

Run `python -m scripts.seed`, then start the mock bank with `uvicorn mock_bank_api.main:app --port 9100` and the API with `uvicorn app.main:app --reload --port 8000` (separate terminals; keep the SQLite/storage variables set in the API terminal). `frontend/vite.config.js` defaults its API proxy to `http://localhost:8000`; set `VITE_API_PROXY_TARGET` if the API uses another local address. The local storage adapter uses expiring signed links. To run the verification workflow inline on upload without Redis, a Celery worker, or Beat, set `CELERY_TASK_ALWAYS_EAGER=true` in the API terminal before starting it; the upload request waits for the workflow to finish. In this explicit local mode, retry can take over a workflow lease, so do not run a Celery worker at the same time. This is for local development only and still requires a working OCR provider and document storage. Without a working OCR key/provider, fields are filled manually; agent LLM remains on deterministic fallback until separately configured. Mailhog is optional: alerts are recorded even if SMTP is unavailable. For Mailhog outside Docker, set `SMTP_HOST`/`SMTP_PORT` to a local SMTP relay. In another terminal run `cd frontend; npm install; npm run dev`.

The automated live sequence is available after seeding: `docker compose exec backend python -m scripts.demo_flow`. It uploads the genuine SBI reference scan with matching demo values, waits for the verification report, exercises officer approval, sends a T-90 test alert, checks Mailhog, and completes a refund decision. The corresponding pytest integration test is opt-in with `FDR_INTEGRATION_URL=http://localhost:8000`.

## Local checks

```powershell
cd backend
python -m pytest -q
cd ..\frontend
npm install
npm run build
```
