# FDR-Shield

AICTE security deposit and fixed deposit receipt (FDR) management demo. It uses FastAPI, async SQLAlchemy, PostgreSQL, Redis/Celery, MinIO, a React/Vite portal, a pluggable OCR adapter (Ollama vision by default), and a seeded demo bank gateway. The gateway is mock-only; no real bank systems are called. The default Python/Docker dependencies contain no torch, EasyOCR, or Tesseract.

## Run with Docker Compose

Requirements: Docker Engine with the Compose plugin.

```powershell
docker compose up --build -d
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed
docker compose exec backend python -m scripts.backfill_workflows
docker compose exec backend python -m scripts.demo_flow
```

Open the frontend at http://localhost:5173, API docs at http://localhost:8000/docs, MinIO console at http://localhost:9001, Mailhog at http://localhost:8025, and the mock bank docs at http://localhost:9100/docs. The development seed includes demo accounts; production bootstrapping must use the one-time Admin CLI and account invitations.

The checked-in `backend/.env.example` contains development-only compose values. Demo seeding is blocked outside dev/test. For a non-demo database, migrate first, configure unique secrets, then run `python -m scripts.create_admin` once with `INITIAL_ADMIN_EMAIL` and `INITIAL_ADMIN_PASSWORD`; remove that password from the environment afterward. Production requires `APP_ENV=prod`, `COOKIE_SECURE=true`, a valid `MFA_ENCRYPTION_KEY`, `FRONTEND_ORIGIN`, and matching `CORS_ORIGINS` behind HTTPS. The bootstrap Admin must change the initial password.

After migrating an existing database, run the idempotent `backfill_workflows` script before relying on the new status projections. It imports a current-state snapshot only; legacy node-level run history cannot be reconstructed. New FDR submissions now enter a PostgreSQL-backed workflow via a transactional outbox; Celery executes persisted extraction, validation and routing nodes, records checkpoints/errors, retries transient failures, waits for corrections/official review, and reclaims expired worker leases. Reminder/correction email delivery also uses the outbox; ambiguous SMTP sends after a dispatcher crash are marked uncertain/dead rather than blindly resent. Workflow inspection/replay APIs and debugger UI, a command center and agents remain future work.

Authentication uses separate portals at `/institution/login`, `/official/login`, and `/admin/login`. Access and rotating refresh tokens are HttpOnly cookies; browser state stores only the user profile. Unsafe cookie-authenticated calls use a signed double-submit CSRF token. Institution users can self-register, verify email, and then wait for Admin approval. Admin-created users receive a one-time invite to set a password. In local Compose, invitation, verification and reset emails can be inspected in Mailhog.

The Official portal now includes a persisted workflow control room, exception inbox, SSE progress, and a natural-language Command Center. Until an LLM provider/key is configured, command interpretation is an offline, typed deterministic allowlist; unknown or financial-approval commands are refused. Commands resolve case references on the server, show a plan, require confirmation for mutations, and execute through Celery. No release/refund approval is available as an agent command.

### Ollama vision modes

- **Local Ollama signed in for cloud models:** install/start Ollama on the host, run `ollama signin`, confirm `gemma4:cloud` appears in `ollama list`, and leave `OLLAMA_BASE_URL=http://host.docker.internal:11434` with `OLLAMA_API_KEY` empty. Compose maps `host.docker.internal` to the host gateway.
- **Direct Ollama API:** set `OLLAMA_BASE_URL=https://ollama.com`, `OLLAMA_MODEL=gemma4:cloud`, and provide `OLLAMA_API_KEY` in an untracked local environment file. Never commit the API key.

Set `OCR_ENGINE=easyocr` only after installing `backend/requirements-ml.txt`; choose `tesseract` only when both the optional Python binding and system binary are installed. `cnn` is reserved for a future adapter.

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
2. Watch the verification report: OCR is compared against the declaration and the mock bank; trust badges settle to green, amber, or red. This uses `gemma4:cloud` through the configured Ollama endpoint.
3. Sign in as `officer@example.test`, inspect the SplitViewer and approve/reject; use `admin@example.test` to fire `POST /api/v1/notifications/test?fdr_id=<id>&stage=T-90` and check Mailhog at http://localhost:8025.
4. Use a matured, verified FDR to request a refund, then sign in as either AICTE Official account to approve/reject. Audit entries are visible in the Bureau portal.

## No-Docker Windows demo

Install Python 3.11+, Node.js 20+, and Ollama on the host. PostgreSQL/Redis are optional for the demo (SQLite + Celery eager mode are supported). From `backend`, create a virtual environment and install `requirements.txt`. Set these environment variables in the backend PowerShell session:

```powershell
$env:DATABASE_URL='sqlite+aiosqlite:///./fdrshield.db'
$env:STORAGE_BACKEND='local'
$env:STORAGE_LOCAL_PATH='./var/fdr-documents'
$env:CELERY_TASK_ALWAYS_EAGER='true'
$env:MOCK_BANK_URL='http://127.0.0.1:9100'
$env:SMTP_HOST='127.0.0.1'
```

Run `python -m scripts.seed`, then start the mock bank with `uvicorn mock_bank_api.main:app --port 9100` and the API with `uvicorn app.main:app --reload --port 8000` (separate terminals; keep the SQLite/storage variables set in the API terminal). `frontend/vite.config.js` defaults its API proxy to `http://localhost:8000`; set `VITE_API_PROXY_TARGET` if the API uses another local address. The local storage adapter uses expiring signed links; OCR still requires Ollama. Mailhog is optional: alerts are recorded even if SMTP is unavailable. For Mailhog outside Docker, set `SMTP_HOST`/`SMTP_PORT` to a local SMTP relay. In another terminal run `cd frontend; npm install; npm run dev`.

The automated live sequence is available after seeding: `docker compose exec backend python -m scripts.demo_flow`. It uploads the generated SBI scan, waits for the verification report, exercises officer approval, sends a T-90 test alert, checks Mailhog, and completes a refund decision. The corresponding pytest integration test is opt-in with `FDR_INTEGRATION_URL=http://localhost:8000`.

## Local checks

```powershell
cd backend
python -m pytest -q
cd ..\frontend
npm install
npm run build
```
