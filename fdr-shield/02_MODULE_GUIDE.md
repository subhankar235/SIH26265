# NidhiTrack: Module Guide (for Codex / Claude Code)

Every file is a **stub**: signatures + comments saying what to implement (`raise NotImplementedError` / `throw new Error`). Replace stubs one by one. Read `01_HLD_LLD.md` first for the design.

## 0. Conventions
- Backend is async SQLAlchemy 2.0 + FastAPI. Services take `session: AsyncSession` first.
- Routers: validate and authorize only, then call a service. Services: logic + audit. No DB calls in routers.
- Statuses/roles/badges come from `app/core/enums.py`; never hard-code strings elsewhere.
- Add missing imports when implementing (stubs list only the main ones; Pydantic types like `FDRCreate` live in `app/schemas/`).
- The frontend only talks to the backend through `src/api/*`; components use hooks, hooks use api.

## 1. Folder map

```
fdr-shield/
├── 01_HLD_LLD.md / 02_MODULE_GUIDE.md / README.md
├── docker-compose.yml, Makefile, .gitignore
├── backend/
│   ├── app/
│   │   ├── main.py                 app factory, routers, startup
│   │   ├── core/                   config, database, security, deps, middleware, exceptions, enums
│   │   ├── models/                 SQLAlchemy tables
│   │   ├── schemas/                Pydantic DTOs
│   │   ├── api/v1/                 HTTP routers
│   │   ├── services/               business logic
│   │   ├── integrations/           storage, email, telegram, whatsapp mock, digilocker mock, OCR engines
│   │   └── workers/                Celery app + tasks
│   ├── mock_bank_api/              separate DEMO CBS FastAPI service
│   ├── migrations/ scripts/ tests/
└── frontend/
    └── src/ api/ store/ hooks/ utils/ routes/ components/{layout,common,charts,fdr,refund} pages/{auth,institution,bureau,admin}
```

## 2. Backend, file by file

### core/
| File | Build |
|---|---|
| `config.py` | `Settings` from env; `get_settings()` cached |
| `database.py` | async engine, `Base`, `get_session` dependency |
| `security.py` | Argon2id + legacy bcrypt verification, JWT, CSRF, encrypted TOTP helpers |
| `deps.py` | Cookie-backed `get_current_user`, `require_roles`, pagination, client IP |
| `middleware.py` | request id + request logging |
| `exceptions.py` | domain errors -> JSON responses |
| `enums.py` | Role, FDRStatus, TrustBadge, AlertStage (already complete) |

### models/ (already real SQLAlchemy columns; add relationships/indexes as needed)
`user`, `institution`, `fdr`, `document`, `discrepancy`, `audit_log`, `notification`, `refund_request`, plus refresh token, one-time token and login-attempt records for manual authentication.

Phase 1 adds `workflow_instance`, `workflow_node_execution`, `workflow_event`, `workflow_checkpoint`, `outbox_event`, `verification_run`, `approval_record`, `exception_item`, `correction_request`, automation rule/version, command execution and notification delivery-attempt records. `fdrs.status` remains the compatibility field; lifecycle and verification provenance are separate. The workflow tables are persistence groundwork and do not yet provide an executor, replay API or workflow UI.

### schemas/
One file per domain; fill Pydantic fields listed in each `# TODO`. Use `model_config = ConfigDict(from_attributes=True)` for `*Out` types.

### api/v1/ (routers)
| Router | Calls | Notes |
|---|---|---|
| `auth.py` | `security`, user lookup | MFA is two-step: temp token then full token |
| `institutions.py` | `institution_service` | institution role only sees its own |
| `fdrs.py` | `fdr_service`, `document_service`, `workers.tasks_verification` | `submit_fdr` enqueues OCR task |
| `documents.py` | `document_service` | |
| `verification.py` | `fraud_service`, `trust_score_service`, worker task | report = ocr + bank + discrepancies |
| `notifications.py` | `notification_service`, `tasks_maturity.send_alert_task` | `/test` for demo |
| `refunds.py` | `refund_service` | |
| `dashboard.py` | `dashboard_service` | Redis cache |
| `audit.py` | `audit_service.query_logs` | read-only |
| `router.py` | all above | mounts at `/api/v1` |

### services/ (business logic)
| Service | Responsibility | Depends on |
|---|---|---|
| `fdr_service` | create, list, `ALLOWED_TRANSITIONS`, renewal | `audit_service` |
| `document_service` | validate + store uploads, presign | `storage_client` |
| `ocr_service` | PDF/image scan -> validated `OcrResult` | `integrations/ocr/base.py`, `get_engine()` |
| `fraud_service` | compare declared/OCR/bank -> discrepancies | `rapidfuzz` |
| `bank_verification_service` | call mock bank | `httpx`, `mock_bank_api` |
| `trust_score_service` | badge + status from discrepancies/bank | `fraud_service` output |
| `notification_service` | stages, templates, dispatch, escalate | `email_client`, `telegram_client`, `whatsapp_mock` |
| `refund_service` | eligibility + decision | `fdr_service`, `audit_service` |
| `dashboard_service` | aggregates + Redis cache | |
| `institution_service` | CRUD/search | |
| `audit_service` | append-only `record`, `query_logs` | |

### integrations/
`storage_client` (boto3/MinIO or local folder), `email_client` (aiosmtplib), `telegram_client` (httpx), `whatsapp_mock`, `digilocker_mock`, `ocr/base.py`, `ocr/ollama_vision_engine.py` (optional), optional `ocr/easyocr_engine.py` and `ocr/tesseract_engine.py`, `ocr/cnn_engine.py` (future adapter), `templates/maturity_alert.html`.

OCR uses the unchanged `FdrExtractor` method signature: `async extract(pages: list[bytes]) -> dict`, returning seven nullable fields including `branch`; `extract_fdr_fields` and `get_engine` retain their signatures. The Ollama adapter may additionally return `document_format` (`fdr_like`, `not_fdr_like`, or `uncertain`) and a short reason. With `OCR_FORMAT_CHECK=true` (default), it screens up to two candidate pages for bank-neutral FDR-like structure; it does not require or compare SBI/HDFC/PNB templates. This is only an appearance-based document check, never bank verification or proof of authenticity. Extracted fields are retained even if the screen is negative or uncertain. Exact hashes from `negative_samples/` short-circuit known synthetic negative fixtures; `OCR_REFERENCE_DIR` resolves that fixture directory relative to the backend root. Bare Settings default to `OCR_ENGINE=disabled`; Compose selects `ollama_vision` at Ollama Cloud. For offline OCR, install `requirements-ml.txt`; those adapters extract fields but report format screening as not checked. Future CNN adapters plug into the same engine interface. OCR errors preserve an unverified record and allow manual review.

### workers/
| File | Build |
|---|---|
| `celery_app.py` | Celery + beat schedule (`scan_maturities` daily 02:00) |
| `tasks_verification.py` | `run_verification_pipeline(fdr_id)`: OCR -> bank -> fraud -> badge -> audit |
| `tasks_maturity.py` | `scan_maturities()` and `send_alert_task()` |
Celery tasks are sync entry points: wrap async service calls with `asyncio.run(...)`.

### workflow state foundation
`services/workflow_state_service.py` maintains the lifecycle/status projection, creates workflow instances for new cases and appends status events/outbox intents. `services/outbox_service.py` dispatches due jobs and notification intents. `workflows/definition.py`, `workflows/transitions.py` and `workers/tasks_workflow.py` execute the persisted extract/validate/route nodes, with worker leases, node attempts, checkpoints and correction/official wait states. `scripts/backfill_workflows.py` idempotently imports legacy state, document versions, verification snapshots and auditable human decisions. Imported executions are marked `not_started`; historical node attempts cannot be reconstructed.

`api/v1/workflows.py` exposes case/node/event/checkpoint reads, SSE, exception inbox, approval, claim, pause/resume, retry/replay/version and comparison endpoints. `api/v1/commands.py` provides a typed allowlisted command plan/confirm/cancel/history/stream flow. `COMMAND_LLM_ENABLED=false` by default. When explicitly configured, the Command Center uses an OpenAI-compatible LLM for structured intent parsing; missing/malformed/unavailable provider output falls back to the deterministic parser. The institution assistant similarly falls back to its deterministic response. All generated output remains constrained by server allowlists, scoped data, role checks and confirmation. Official pages include `WorkflowControlRoom`, `WorkflowExecution`, `ExceptionInbox`, and `CommandCenter`.

Public Institution and AICTE Official applications enter their approval queues immediately; email verification is temporarily disabled. AICTE Officials decide Institution applications; the Super Admin (stored role `admin` for backward compatibility) approves/rejects Official applications and may decide Institution applications directly. Public application decisions can be audit-logged and overridden by a Super Admin. The one-time setup page at `/super-admin/setup` posts to `/api/v1/auth/register/super-admin`; it requires `SUPER_ADMIN_SETUP_SECRET` in the backend environment, stores only an Argon2id password hash, and uses the same PostgreSQL advisory/SQLite immediate lock as the CLI bootstrap. It closes permanently after a Super Admin row is created; no additional public Super Admin signup is available.

### mock_bank_api/ (DEMO, separate service)
`main.py` mounts `banks/sbi.py`, `pnb.py`, `hdfc.py`; `store.py` loads `data/seed_fdrs.json`. Each bank may return slightly different field names; `bank_verification_service` normalizes them to `BankVerifyResponse`. **Never call real bank APIs.**

## 3. Frontend, file by file
| Folder | Build |
|---|---|
| `api/` | thin Axios wrappers, one per backend router; no UI logic |
| `store/` | `authStore` (in-memory user/session state only), `uiStore` (filters, sidebar) |
| `hooks/` | React Query hooks wrapping `api/*`; `useMaturityCountdown` |
| `utils/` | `formatINR`, `formatDate`, `getBadgeMeta`, `getStatusMeta` |
| `components/common` | `MetricCard`, `TrustBadge`, `StatusPill`, `DataTable`, `FileDropzone`, `RoleGuard`, `ConfirmDialog` |
| `components/charts` | Recharts donut / timeline / bank bar |
| `components/fdr` | `FdrUploadForm`, `TrustMatrixTable`, `FdrDetailCard`, **`SplitViewer`**, `DiscrepancyList`, `RenewalRequestForm`, `MaturityCountdown` |
| `components/refund` | `RefundForm`, `RefundDecisionPanel` |
| `pages/auth` | `Login`, `MfaVerify` |
| `pages/institution` | `InstitutionDashboard`, `UploadFdr`, `MyFdrs`, `RefundClaim` |
| `pages/bureau` / `pages/admin` | Official scrutiny pages and Admin account, registration and institution screens |
| `routes/AppRoutes.jsx` | route table in the comment; wrap with `RoleGuard` |

### Phase 12 role-based UI routes
- Institution portal: `/institution`, `/institution/fdrs/new`, `/institution/fdrs`, `/institution/fdrs/:id`, `/institution/renewals`, `/institution/releases`, `/institution/notifications`; the assistant drawer is available across institution routes.
- Official portal: `/official/queue`, `/official/review/:id`, `/official/control-room`, `/official/workflows/:id`, `/official/exceptions`, `/official/approvals`, `/official/command`, `/official/audit`.
- Admin portal: `/admin/users`, `/admin/institutions`, `/admin/roles`, `/admin/dashboard`, `/admin/rules`, `/admin/alerts`, `/admin/jobs`, `/admin/health`, `/admin/audit`, `/admin/ops-agent`.
- Shared UI states include retryable errors with request IDs, loading skeletons, guided empty states, accessible confirmation dialogs, status icons/text and success toasts. Workflow and exception views use SSE with polling fallback; data endpoints without an SSE feed poll on an interval. Institution notification read markers are browser-local because notification records do not have a user read-state column.

### Phase 13 data-dependent ML and Phase 14 hardening
- Run Gate 0 from the admin ML governance page/API before any trainer work. Real training rows require explicit `is_synthetic=false`; legacy `NULL` provenance is excluded. Synthetic samples are isolated in `ml_demo_samples`, always labeled, and cannot enter Gate 0 hashes or real metrics.
- Gate plans specify target, feature version, missing policy, data minima, evaluation metrics, acceptance thresholds and deterministic fallback. No training dependency/model is currently shipped; gates only record blocked/eligible-for-review states. Eligibility does not enable authorization-affecting inference.
- Deterministic inference stores only advisory `ml_predictions`; all rows include origin and predictor metadata. Periodic ops snapshots are labeled synthetic in dev/test; weekly audit export validates the SHA-256 chain before writing to private object storage.
- `CLAMAV_HOST` enables pre-storage ClamAV INSTREAM scanning. If configured but unavailable, upload fails closed. Without it, normal MIME/magic/size checks remain and no AV scan is claimed.
- Redis rate limits guard OCR preview, command and assistant endpoints; a bounded per-worker fallback applies on Redis failure. Request IDs are sanitized, carried into audit records and structured HTTP logs; do not add prompt/document contents to logs.
- Compose targets Ollama Cloud for OCR only; add `OLLAMA_API_KEY` to `backend/.env`. Agent LLM calls use separate `COMMAND_LLM_ENABLED`, `COMMAND_LLM_API_URL`, `COMMAND_LLM_MODEL`, and `COMMAND_LLM_API_KEY` settings and remain disabled until configured. Compose applies the private `.env` override over the checked-in example. Provider outages preserve deterministic fallbacks; no model can directly execute tools or bypass confirmation.
- MinIO uploads use container `S3_ENDPOINT`; generated presigned document links use browser-reachable `S3_PUBLIC_ENDPOINT` so a browser never receives the Compose-only `minio` hostname.
- PostgreSQL backups can be created with `python scripts/postgres_backup.py backup <private-path.dump>` and restore-tested only against a separate disposable database using `RESTORE_DATABASE_URL=<disposable-url> python scripts/postgres_backup.py verify-restore <path>`. Credentials are read from the environment, not argv; the helper verifies SHA-256 and migration/audit/FDR counts, does not delete backups, and requires deployment-owned retention, encryption and offsite policy.

## 4. How modules communicate

### 4.1 Runtime call chains
```
UI page -> hook (useFdrs) -> api/fdr.api.js -> axios -> /api/v1/fdrs
   -> router fdrs.py -> fdr_service -> models (PG) + audit_service
                     -> document_service -> storage_client (MinIO)
                     -> tasks_verification.delay(fdr_id)   [Redis queue]

Worker: tasks_verification
   -> storage_client.get -> ocr_service -> get_engine() (Ollama vision by default)
   -> bank_verification_service -> HTTP -> mock_bank_api
   -> fraud_service -> discrepancies table
   -> trust_score_service -> fdr.trust_badge/status
   -> audit_service

Beat: tasks_maturity.scan_maturities
   -> fdr query -> notification_service -> email_client / telegram_client / whatsapp_mock
   -> notifications table + AICTE Official escalation

Dashboard: BureauDashboard -> useBureauDashboard -> /dashboard/bureau
   -> dashboard_service -> SQL aggregates (+ Redis cache)
```

### 4.2 Data contracts between modules
| Producer -> Consumer | Contract |
|---|---|
| `ocr_service` -> `fraud_service` | `OcrResult{fdr_number, bank_name, holder_name, amount, issue_date, maturity_date, confidence}` |
| `bank_verification_service` -> `fraud_service`, `trust_score_service` | `BankVerifyResponse{found, status, amount, maturity_date, holder}` |
| `fraud_service` -> `trust_score_service` | `list[DiscrepancyOut]` |
| `trust_score_service` -> API/UI | `TrustBadge` enum value |
| API -> frontend | JSON shaped by `schemas/*Out`; dates ISO-8601, amounts as numbers (INR) |
| Anything that mutates state -> `audit_service.record` | `(user_id, entity, entity_id, action, ip, delta{field:[old,new]})` |

### 4.3 Auth flow
One shared login page at `/login` -> `POST /api/v1/auth/login` with a required `portal` selector -> backend verifies that selector against the matched user's stored role -> HttpOnly session cookies (or short-lived MFA cookie) -> in-memory profile from `/auth/me`; Axios sends credentials and CSRF header. Legacy role-specific login URLs redirect to the shared form; hidden compatibility endpoints bind directly to their portal. Protected APIs independently check active account status and `require_roles`.

## 5. Suggested build order (hackathon, 3 days)
**Day 1 (skeleton that runs):** `core/*` -> `models` + migration -> `auth` router -> `seed.py` -> frontend `Login`, `authStore`, `RoleGuard`, `Layout`.
**Day 2 (USPs):** `mock_bank_api` -> `storage_client` -> `document_service` + `fdrs` submit -> OCR engine + `ocr_service` + `fraud_service` + `trust_score_service` -> `tasks_verification` -> `UploadFdr`, `TrustMatrixTable`, `TrustBadge`.
**Day 3 (wow + polish):** `SplitViewer` + `ScrutinySplitView` -> `tasks_maturity` + `notification_service` + Mailhog -> dashboards/charts -> `AuditLogs` -> refund flow if time permits.

## 6. Working with an AI coding agent
Prompt pattern: *"Implement `backend/app/services/fraud_service.py` per the comments. Follow `01_HLD_LLD.md` section 2.4. Write tests in `backend/tests/test_fraud_service.py`."*
One file per prompt; run `pytest` / `npm run dev` after each; keep contracts in section 4.2 unchanged unless you update both sides and these docs.

## 7. Definition of done (demo)
- [x] Login for 3 roles (institution, AICTE official, admin).
- [x] Upload scan -> OCR data + bank check + badge appear — live Ollama OCR confidence 0.833, mock bank found, green badge, no discrepancy.
- [x] Seeded mismatch shows red badge + discrepancy list — seed creates red HDFC amount mismatches; 13 open seeded discrepancies were returned by the live API.
- [x] Split viewer works; approve/reject updates status and audit log — SplitViewer smoke test passed; live officer approval generated six audit events.
- [ ] `/notifications/test` delivers email (Mailhog) for T-90/T-30/T-0 — T-90 delivered and appeared in Mailhog; T-30 and T-0 delivery not yet exercised live.
- [x] Dashboard metric cards + 3 charts load from real data — dashboard API returned bank, maturity, and status datasets in the live demo.

### OCR engine, storage and demo adapters
- `OCR_ENGINE=ollama_vision` is the Compose/default OCR engine and uses `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, optional `OLLAMA_API_KEY`, and `OLLAMA_TIMEOUT`. `OCR_FORMAT_CHECK=true` enables bank-neutral FDR document-format screening; it does not compare against bank templates and does not prove authenticity. `OCR_REFERENCE_DIR=reference_formats` sets the backend-root-relative known-negative fixture folder. Set format checking false for plain OCR debugging. The model schema carries a format assessment/reason alongside the seven extracted fields.
- Reference files: `sbi/sbi_reference.png`, `hdfc/hdfc_reference.png`, `pnb/pnb_reference.png` are genuine examples; `negative_samples/sample-sbi.png` is a known rejected dummy fixture.
- Optional EasyOCR/Tesseract dependencies are isolated in `requirements-ml.txt`; they are not in the default install or Docker image. Their modules import the libraries lazily.
- To add `cnn_engine.py`, implement `FdrExtractor.extract(pages: list[bytes]) -> dict` from `integrations/ocr/base.py`, return the same seven keys with `None` for missing values, and register the engine name in `integrations/ocr/__init__.py`.
- Docker uses `chainguard/minio:latest`, a named `minio-data` volume and a live healthcheck. `STORAGE_BACKEND=local` selects the local folder adapter for a no-Docker demo; local document links are HMAC-signed and expire after five minutes.
