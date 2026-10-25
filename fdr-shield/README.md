# FDR-Shield

AICTE security deposit and fixed deposit receipt (FDR) management demo. It uses FastAPI, async SQLAlchemy, PostgreSQL, Redis/Celery, MinIO, a React/Vite portal, optional OCR/LLM providers, and a seeded demo bank gateway. The gateway is mock-only; no real bank systems are called. OCR and Command Center LLM are disabled by default, so startup requires no Ollama/cloud account/API key. Manual FDR entry and deterministic command/assistant/ML fallbacks remain available.

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

The checked-in `backend/.env.example` contains development-only compose values. Demo seeding is blocked outside dev/test. For a non-demo database, migrate first, configure unique secrets, then run `python -m scripts.create_admin` once with `INITIAL_ADMIN_EMAIL` and `INITIAL_ADMIN_PASSWORD`; remove that password from the environment afterward. Production requires `APP_ENV=prod`, `COOKIE_SECURE=true`, a valid `MFA_ENCRYPTION_KEY`, `FRONTEND_ORIGIN`, and matching `CORS_ORIGINS` behind HTTPS. The bootstrap Admin must change the initial password.

After migrating an existing database, run the idempotent `backfill_workflows` script before relying on the new status projections. It imports a current-state snapshot only; legacy node-level run history cannot be reconstructed. New submissions enter a PostgreSQL-backed workflow via a transactional outbox; Celery executes extraction, validation and routing nodes, records checkpoints/errors, retries transient failures, waits for corrections/official review, and reclaims expired worker leases. Reminder/correction email delivery uses the outbox; ambiguous SMTP sends after a dispatcher crash are marked uncertain/dead rather than blindly resent. Workflow inspection/replay, SSE, Command Center, scoped assistance/operations agents and role-based screens are implemented in the current React app.

## Verification, ML gates, and operations runbook

See [`docs/phase15-17-verification.md`](docs/phase15-17-verification.md) for test coverage, injection procedures, deployment/rollback steps, acceptance target status and the Phase 17 demo scope. Current local checks are `python -m pytest -q` from `backend`, plus `npm test` and `npm run build` from `frontend`. There is no configured frontend lint script. ML Gate 0 is available from Admin → ML governance / `/admin/ml`; models are not trained until real historical data volume and review criteria qualify. Seeded rows and generated examples are marked synthetic and excluded from real aggregate metrics.

### Optional LLM agents

The Command Center and institution assistant do not contact an LLM by default. If you later choose a provider, set `COMMAND_LLM_ENABLED=true`, `COMMAND_LLM_API_URL`, and `COMMAND_LLM_MODEL` in the backend environment; set `COMMAND_LLM_API_KEY` only if your chosen provider requires it. Keep these credentials out of frontend `VITE_*` variables. If the provider is missing, unavailable, times out, or returns invalid output, command and assistant responses fall back to deterministic behavior. Mutating actions always require server authorization and confirmation.

Authentication uses separate portals at `/institution/login`, `/official/login`, and `/admin/login`. Access and rotating refresh tokens are HttpOnly cookies; browser state stores only the user profile. Unsafe cookie-authenticated calls use a signed double-submit CSRF token. Institution users can self-register, verify email, and then wait for Admin approval. Admin-created users receive a one-time invite to set a password. In local Compose, invitation, verification and reset emails can be inspected in Mailhog.

The Official portal now includes a persisted workflow control room, exception inbox, SSE progress, and a natural-language Command Center. By default, command interpretation is an offline, typed deterministic allowlist; unknown or financial-approval commands are refused. If an LLM is configured, its output is still constrained to the typed allowlist. Commands resolve case references on the server, show a plan, require confirmation for mutations, and execute through Celery. No release/refund approval is available as an agent command.

### Optional OCR

`OCR_ENGINE=disabled` is the default. Upload/review still works, but extracted fields are blank and must be entered/confirmed manually. This mode makes no model call. To use OCR later, choose an available provider explicitly (`ollama_vision`, `easyocr`, or `tesseract`) and configure/install its requirements. If OCR fails, the record remains unverified with no extracted values; it is not treated as a verification failure or authenticity finding.

## Demo accounts

`python -m scripts.seed` creates the following development-only demo users. Password for each is `DemoPass123!`.

| Role | Email |
|---|---|
| Institution 1 | `institution1@example.test` |
| Institution 2–5 | `institution2@example.test` through `institution5@example.test` |
| AICTE Official | `officer@example.test` or `chief@example.test` |
| Admin | `admin@example.test` |

## Four-step demo

1. Sign in with `institution1@example.test` and upload a scan. Seed creates 15 sample records and three scans in `backend/sample_scans` (matching SBI/PNB, plus a deliberately mismatched HDFC sample).
2. Enter/review the FDR fields manually (OCR is disabled by default); verification compares the declared values against the mock bank and updates the trust badge.
3. Sign in as `officer@example.test`, inspect the SplitViewer and approve/reject; use `admin@example.test` to fire `POST /api/v1/notifications/test?fdr_id=<id>&stage=T-90` and check Mailhog at http://localhost:8025.
4. Use a matured, verified FDR to request a refund, then sign in as either AICTE Official account to approve/reject. Audit entries are visible in the Bureau portal.

## No-Docker Windows demo

Install Python 3.11+ and Node.js 20+. PostgreSQL/Redis are optional for the demo (SQLite + Celery eager mode are supported). No Ollama or LLM API key is required in the default configuration. From `backend`, create a virtual environment and install `requirements.txt`. Set these environment variables in the backend PowerShell session:

```powershell
$env:DATABASE_URL='sqlite+aiosqlite:///./fdrshield.db'
$env:STORAGE_BACKEND='local'
$env:STORAGE_LOCAL_PATH='./var/fdr-documents'
$env:CELERY_TASK_ALWAYS_EAGER='true'
$env:MOCK_BANK_URL='http://127.0.0.1:9100'
$env:SMTP_HOST='127.0.0.1'
```

Run `python -m scripts.seed`, then start the mock bank with `uvicorn mock_bank_api.main:app --port 9100` and the API with `uvicorn app.main:app --reload --port 8000` (separate terminals; keep the SQLite/storage variables set in the API terminal). `frontend/vite.config.js` defaults its API proxy to `http://localhost:8000`; set `VITE_API_PROXY_TARGET` if the API uses another local address. The local storage adapter uses expiring signed links. With OCR disabled, fields are filled manually. Mailhog is optional: alerts are recorded even if SMTP is unavailable. For Mailhog outside Docker, set `SMTP_HOST`/`SMTP_PORT` to a local SMTP relay. In another terminal run `cd frontend; npm install; npm run dev`.

The automated live sequence is available after seeding: `docker compose exec backend python -m scripts.demo_flow`. It uploads the generated SBI scan, waits for the verification report, exercises officer approval, sends a T-90 test alert, checks Mailhog, and completes a refund decision. The corresponding pytest integration test is opt-in with `FDR_INTEGRATION_URL=http://localhost:8000`.

## Local checks

```powershell
cd backend
python -m pytest -q
cd ..\frontend
npm install
npm run build
```
