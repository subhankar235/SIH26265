# AICTE FDR Portal — Detailed Step-by-Step Implementation Guide

> Derived from the "Master Prompt: AICTE FDR Portal — Existing Codebase Audit & Complete Implementation Blueprint".
> **Status of this document:** a repository-agnostic execution playbook. I have **not** inspected your repository, so every file path, table name and library below is a *placeholder or recommendation* until Phase 0 verifies it. Items marked `[VERIFY]` must be confirmed against real code before implementing.
> **Rule:** this guide is a plan. Do not modify source files until the plan is reviewed and approved.

---

## 0. How a Coding Agent Must Use This File

1. Execute phases **in order**. Do not start a phase until its prerequisites are "Done".
2. Never claim a file, function, or test exists unless you opened it. Never claim a test passed unless you ran it.
3. Reuse existing auth, DB, storage, OCR, LLM, notification and job infrastructure. Add a dependency only with a written justification (why, already present?, reuse?, cost, migration work).
4. The LLM **proposes**; deterministic backend code **decides**. LLM output is never authority for status, permissions, deadlines, or financial/regulatory decisions.
5. Extracted document text is **untrusted data**, never instructions.
6. Never overwrite execution history. Append-only.
7. Every phase ends with: tests green, acceptance criteria met, rollback documented.
8. Separate **verified facts** / **assumptions** / **recommendations** / **open questions** in every report you write.

### Glossary of trust levels (must be modelled explicitly in data)

| Level | Meaning | Example |
|---|---|---|
| `DECLARED` | Entered by institution | Form field values |
| `EXTRACTED` | Read from a document by OCR/LLM | Parsed FDR number |
| `VERIFIED_EXTERNAL` | Confirmed by authorized independent source | Real bank API (not mock) |
| `AI_RECOMMENDATION` | Model/agent suggestion | "Likely discrepancy" |
| `HUMAN_DECISION` | Authorized official's recorded decision | Approve release |

> Mock bank verification ≠ OCR consistency check ≠ independent bank verification ≠ human scrutiny ≠ final authorized decision. Label each distinctly in UI and DB.

---

## Phase 0 — Repository Audit & Baseline (NO CODE CHANGES)

**Objective:** produce an evidence-based picture of what exists.

### Step 0.1 — Inventory
Run and record output:
```bash
git log --oneline -20 && git status
tree -L 3 -I 'node_modules|.git|__pycache__|.next|venv|.venv'
cat package.json requirements*.txt pyproject.toml 2>/dev/null
ls -la docker* .github/workflows 2>/dev/null
```
Record: frontend root, backend root, worker dirs, shared modules, tests, Docker, CI.

### Step 0.2 — Targeted searches
```bash
grep -rniE "langgraph|langchain|openai|gemini|anthropic" --include=*.py --include=*.ts --include=*.tsx -l .
grep -rniE "celery|redis|apscheduler|rq|bullmq|cron|schedule" -l .
grep -rniE "ocr|tesseract|textract|vision|pdfplumber|pymupdf" -l .
grep -rniE "role|permission|rbac|jwt|session|nextauth" -l .
grep -rniE "alembic|prisma|sqlalchemy|drizzle|migration" -l .
grep -rniE "status|state" --include=*model*.py --include=*schema*.* -n .
grep -rniE "sse|websocket|EventSource|socket.io" -l .
grep -rniE "audit|history|log" -l .
```

### Step 0.3 — Feature matrix (fill in)

| Feature | Location | Status | Missing behaviour | Required change | Depends on | Risk | Tests |
|---|---|---|---|---|---|---|---|
| FDR submission | `[VERIFY]` | | | | | | |
| Document upload/storage | | | | | | | |
| OCR/extraction | | | | | | | |
| Deterministic validation | | | | | | | |
| Verification/scrutiny | | | | | | | |
| Correction request | | | | | | | |
| Renewal tracking | | | | | | | |
| Release/refund | | | | | | | |
| Notifications/reminders | | | | | | | |
| RBAC + institution isolation | | | | | | | |
| Audit history | | | | | | | |
| Background jobs | | | | | | | |
| Agents/LLM | | | | | | | |
| 3 dashboards | | | | | | | |

Allowed statuses: *Implemented and verified · Implemented but unverified · Partially implemented · Missing · Broken · Unclear.*
A file existing does **not** mean the feature works — run it.

### Step 0.4 — Architecture mapping (produce diagrams, Mermaid OK)
- Current architecture; request flow; document-processing flow; FDR lifecycle; notification flow; auth flow; ER diagram.
- List stale docs and inconsistencies.

### Step 0.5 — Baseline run
- Install, run migrations, start app, run existing tests. Record pass/fail honestly.
- Smoke-test: login as each role; submit an FDR; upload a PDF; observe the existing lifecycle.

### Step 0.6 — Role reconciliation
If repo has separate *Scrutiny Officer* / *Bureau Chief* roles: **do not silently merge**. Document (a) current permissions per role, (b) proposed mapping into AICTE Official, (c) migration of existing users, (d) rollback.

### Step 0.7 — Gap analysis
Classify each gap: *Core / Autonomous execution / USP / Optional / Not recommended yet.*

### Step 0.8 — Decisions to record (ADR style)
| Decision | Options | Choose by |
|---|---|---|
| Job runner | existing runner vs Celery+Redis | What exists; simplest reliable |
| Workflow persistence | PostgreSQL job/state tables vs LangGraph checkpointer | Prefer Postgres tables as source of truth |
| Live updates | SSE vs WebSocket | SSE unless bidirectional need |
| LLM provider | existing GPT/Gemini | Whatever is configured |
| Outbox | add vs skip | Add if notifications/external effects exist |

**Recommended default (justify against findings):** PostgreSQL = single source of truth for workflow state; explicit Python state machine for transitions; Celery+Redis (or existing runner) only as the *executor*; transactional outbox for side effects; LangGraph used **only inside** nodes that need multi-step LLM/tool reasoning (Agents A/C, Command planning), not for core transitions.

**Phase 0 Definition of Done:** audit report, feature matrix, diagrams, gap list, ADRs, open-questions list, baseline test results — all reviewed by owner.

---

## Phase 1 — Status Model & Core Data Model

**Objective:** replace/augment a flat status field with separate dimensions, without breaking existing code.

### Step 1.1 — Status dimensions
| Dimension | Purpose | Values (refine against existing) |
|---|---|---|
| `lifecycle_state` | Business stage | SUBMITTED, EXTRACTION_PENDING, EXTRACTING, VALIDATION_PENDING, VALIDATION_FAILED, CORRECTION_REQUIRED, AWAITING_INSTITUTION, READY_FOR_SCRUTINY, UNDER_REVIEW, AWAITING_OFFICIAL_DECISION, ACCEPTED, RENEWAL_REQUIRED, RENEWED, RELEASE_REQUESTED, AWAITING_RELEASE_DECISION, RELEASE_APPROVED, RELEASE_REJECTED, ESCALATED, COMPLETED |
| `execution_state` | Workflow engine | RUNNING, WAITING_EVENT, WAITING_TIMER, WAITING_HUMAN, PAUSED, RETRYING, FAILED, BLOCKED, CANCELLED, COMPLETED |
| `authorization_state` | Human gate | NOT_REQUIRED, PENDING, APPROVED, REJECTED |
| `verification_level` | Trust | DECLARED, EXTRACTED, MOCK_VERIFIED, VERIFIED_EXTERNAL, HUMAN_SCRUTINIZED |

Keep old `status` column; write a **mapping function** old→new and a compatibility view. Backfill via migration; do not drop old column in this phase.

### Step 1.2 — New/changed tables (verify none duplicate existing ones)

**`workflow_instance`**
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| fdr_id | FK → fdr (indexed) | |
| institution_id | FK | denormalized for isolation checks |
| workflow_version | text | definition version |
| execution_version | int | increments on "new execution version" |
| lifecycle_state / execution_state / authorization_state | enum/text | CHECK constraints |
| current_node | text | |
| paused_by, paused_reason | nullable | |
| next_wake_at | timestamptz nullable | index for timers |
| created_at, updated_at, completed_at | timestamptz | |
| version | int | optimistic lock |
Unique: (fdr_id, execution_version).

**`workflow_node_execution`** (append-only)
id UUID PK · instance_id FK · node_key · attempt int · parent_execution_id FK self · replay_of_id FK self · status (PENDING/RUNNING/SUCCEEDED/FAILED/SKIPPED/CANCELLED) · input_ref (JSONB or object-storage key) · output_ref · input_hash · error_class · error_code · error_message · diagnostics JSONB (sanitized) · idempotency_key (UNIQUE where side-effecting) · started_at · finished_at · duration_ms · rule_version · workflow_version · triggered_by (system/user_id) · reason text.
Indexes: (instance_id, started_at), (status), UNIQUE(idempotency_key).

**`workflow_event`** (append-only inbox of triggers)
id · instance_id · type (e.g. `FDR_SUBMITTED`, `DOCUMENT_UPLOADED`, `CORRECTION_RECEIVED`, `OFFICIAL_DECISION`, `TIMER_FIRED`, `RENEWAL_DUE`) · payload JSONB · dedupe_key UNIQUE · received_at · processed_at.

**`workflow_checkpoint`**
id · instance_id · node_execution_id · state_snapshot JSONB (versioned schema) · created_at. Immutable.

**`outbox`**
id · aggregate_id · type (SEND_NOTIFICATION, …) · payload · idempotency_key UNIQUE · status (PENDING/SENT/FAILED/DEAD) · attempts · next_attempt_at · last_error · created_at. Written in the **same transaction** as the state change.

**`notification` / `notification_delivery_attempt`** — reuse existing if present; add `idempotency_key`, `channel`, `status`, `attempt_no`, `provider_response`.

**`approval_record`** (immutable)
id · instance_id · fdr_id · request_type (VALIDATION_ACCEPT, RENEWAL, RELEASE…) · decision (APPROVE/REJECT/REQUEST_CORRECTION/ESCALATE) · rationale (required) · actor_user_id · actor_role · recommendation_ref (nullable) · created_at.

**`exception_item`**
id · instance_id · reason_code · priority · due_at · status (OPEN/CLAIMED/RESOLVED) · evidence_refs JSONB · recommended_action · assigned_to · created_at · resolved_at.

**`audit_event`** (append-only, hash-chained recommended)
id · ts · actor_type (USER/SYSTEM/AGENT) · actor_id · on_behalf_of · action · entity_type · entity_id · institution_id · before JSONB · after JSONB · request_id · prev_hash · hash. Revoke UPDATE/DELETE from app DB role.

**`automation_rule` / `automation_rule_version`**
Versioned rules (reminder offsets, escalation SLAs). Rows never edited; new version inserted.

**`command_execution`**
id · user_id · raw_command · interpreted_plan JSONB · plan_hash · authorization_result JSONB · requires_confirmation bool · confirmed_by/at · status (PLANNED/CONFIRMED/RUNNING/SUCCEEDED/FAILED/CANCELLED) · steps JSONB · result_summary · created_at.

**`ml_model_version` / `ml_prediction`** (only in Phase 13): model name, version, data hash, metrics JSON, `is_synthetic_trained`, status; predictions: entity, score, features_ref, model_version_id, created_at.

**Documents:** if single-file-per-FDR today, add `document_version` (id, fdr_id, version_no, storage_key, sha256, mime, uploaded_by, uploaded_at, supersedes_id).

### Step 1.3 — Migration strategy
1. Additive migrations only (new tables/nullable columns).
2. Backfill in a separate, resumable script.
3. Dual-write period if old status is still read.
4. Rollback = down-migration drops new tables; old columns untouched.
5. Test migration on a copy of real/seed data first.

**Acceptance:** migrations up/down clean; existing tests still pass; CHECK constraints reject illegal combos; no data loss on backfill.

---

## Phase 2 — Audit, Events & Transactional Outbox Foundations

**Objective:** guarantee traceability and no duplicate side effects before adding automation.

Steps:
2.1 Implement `audit.record(actor, action, entity, before, after)` helper; call from every state-changing service.
2.2 Make `audit_event` append-only (DB permissions + trigger blocking UPDATE/DELETE).
2.3 Implement `events.publish(instance_id, type, payload, dedupe_key)` — insert with `ON CONFLICT DO NOTHING`.
2.4 Implement `outbox.enqueue(..., idempotency_key)` called inside the business transaction.
2.5 Implement an outbox dispatcher: `SELECT … FOR UPDATE SKIP LOCKED`, send, mark SENT; backoff on failure; DEAD after N attempts.
2.6 Idempotency key convention: `"{effect_type}:{fdr_id}:{execution_version}:{node_key}:{business_discriminator}"` (e.g. reminder offset or discrepancy hash).

**Interaction rules:** state change + outbox row commit atomically; worker crash after send but before mark-SENT → provider-level idempotency key or "check-before-send" delivery log; consumers must tolerate at-least-once.

**Tests:** duplicate event → one effect; dispatcher crash mid-batch → no double send; audit cannot be updated.
**Done when:** every existing mutation path writes audit; outbox proven duplicate-safe.

---

## Phase 3 — Workflow Engine Core (State Machine + Worker)

**Objective:** durable, restart-safe execution independent of the browser.

### Step 3.1 — Define workflow definition (code, versioned)
```python
# workflow/definition.py  [new path — VERIFY against repo layout]
WORKFLOW_VERSION = "fdr-v1"
NODES = {
  "extract_document":   {"side_effects": False, "retry": {"max": 3, "backoff": "exp"}},
  "validate_fields":    {"side_effects": False},
  "route_case":         {"side_effects": False},
  "request_correction": {"side_effects": True},   # sends notification
  "wait_institution":   {"wait": "event:CORRECTION_RECEIVED", "timeout": "rule:correction_sla"},
  "prepare_scrutiny_summary": {"side_effects": False},
  "human_review":       {"wait": "event:OFFICIAL_DECISION", "human": True},
  "schedule_maturity_alerts": {"side_effects": True},
  "escalate":           {"side_effects": True},
}
```

### Step 3.2 — Allowed transitions (deterministic table)
| From | Event/Condition | To |
|---|---|---|
| SUBMITTED | workflow started | EXTRACTION_PENDING |
| EXTRACTION_PENDING | worker claims | EXTRACTING |
| EXTRACTING | success | VALIDATION_PENDING |
| EXTRACTING | non-recoverable fail | FAILED/BLOCKED (exception created) |
| VALIDATION_PENDING | all required OK, no discrepancy | READY_FOR_SCRUTINY |
| VALIDATION_PENDING | discrepancy/missing | VALIDATION_FAILED → CORRECTION_REQUIRED |
| CORRECTION_REQUIRED | notification enqueued | AWAITING_INSTITUTION |
| AWAITING_INSTITUTION | CORRECTION_RECEIVED | EXTRACTION_PENDING (new document version) |
| AWAITING_INSTITUTION | SLA timer | ESCALATED |
| READY_FOR_SCRUTINY | official opens | UNDER_REVIEW |
| UNDER_REVIEW | needs decision | AWAITING_OFFICIAL_DECISION |
| AWAITING_OFFICIAL_DECISION | APPROVE (authorized) | ACCEPTED |
| … | REQUEST_CORRECTION | CORRECTION_REQUIRED |
| ACCEPTED | maturity − N days | RENEWAL_REQUIRED |
| RENEWAL_REQUIRED | renewal doc validated | RENEWED |
| ACCEPTED/RENEWED | release request | RELEASE_REQUESTED → AWAITING_RELEASE_DECISION |
| AWAITING_RELEASE_DECISION | authorized approve/reject | RELEASE_APPROVED / RELEASE_REJECTED → COMPLETED |

Implement as a single `transition(instance, event, actor)` function that: checks permission → checks guard → updates with optimistic lock → writes audit → writes outbox → commits. Illegal transition raises `IllegalTransition` (HTTP 409).

### Step 3.3 — Worker loop
1. Claim runnable instances: `WHERE execution_state IN ('RUNNING','RETRYING') OR (execution_state LIKE 'WAITING_%' AND next_wake_at <= now())` using `FOR UPDATE SKIP LOCKED`.
2. Write `workflow_node_execution(status=RUNNING)` and commit **before** executing.
3. Execute node (pure function of persisted input).
4. On success: persist output + checkpoint + transition in one transaction.
5. On failure: classify (below), write structured error, schedule retry or create exception.
6. Heartbeat/lease column; a reaper marks RUNNING executions with expired lease as `FAILED(error_class=WORKER_LOST)` and re-queues.

### Step 3.4 — Failure classification
| Class | Examples | Action |
|---|---|---|
| TRANSIENT | timeout, 5xx, rate limit | auto-retry w/ exponential backoff + jitter, max N |
| INPUT | unreadable/corrupt PDF | no auto retry → exception "request new document" |
| VALIDATION | business rule failure | not an error; route branch |
| PERMANENT | bug, schema mismatch | dead-letter + exception + admin alert |
| WORKER_LOST | crash/lease expiry | retry same operation |

### Step 3.5 — Scheduler
Periodic job (e.g., every 5 min) scans `fdr.maturity_date` + `automation_rule` offsets and publishes `RENEWAL_DUE` / `REMINDER_DUE` events using dedupe keys (`reminder:{fdr}:{offset}:{maturity_date}`). Date arithmetic in one tested module with explicit timezone (`Asia/Kolkata` for business dates) `[VERIFY business-day rules]`.

### Step 3.6 — Starting a workflow
On FDR submit: in the **same transaction** create `workflow_instance` + `FDR_SUBMITTED` event. Never start by calling the worker inline.

**Tests:** transition table exhaustive; kill worker mid-node → recovery; two workers → one claim; timers fire once.
**Acceptance (proposed targets):** 100% of illegal transitions rejected in unit tests; killing a worker mid-execution results in completion without duplicate side effects in N=50 randomized runs.

---

## Phase 4 — Extraction & Validation Nodes (Reuse Existing OCR)

Steps:
4.1 Wrap existing OCR/extraction as node `extract_document`; output typed `ExtractionResult { fields: {name: {value, confidence, source_span, trust: EXTRACTED}}, raw_ref, extractor_version }`.
4.2 Deterministic `validate_fields` in plain Python: required fields present; date parse & ordering (issue < maturity); amount positive/format; declared vs extracted equality; bank allowlist; duplicate FDR number across institutions; maturity not already past.
4.3 Output `ValidationResult { passed, discrepancies[{field, declared, extracted, severity, rule_id, rule_version}] }`.
4.4 Prompt-injection hardening: if an LLM is used for extraction, put document text in a delimited data block; require JSON schema output; reject non-conforming output; strip any "instructions" in doc; LLM has **no tools** in extraction.
4.5 Never set `verification_level` above `EXTRACTED`/`MOCK_VERIFIED` from this phase.

**Tests:** golden PDFs (clean, missing field, mismatched amount, malicious "ignore previous instructions" text, corrupted PDF). **Acceptance:** malicious text never alters validation result or triggers a tool.

---

## Phase 5 — Waiting, Resumption & Notifications

Steps:
5.1 `wait_institution`: set `execution_state=WAITING_EVENT`, store awaited event type, timeout via `next_wake_at`.
5.2 On document upload API: create `document_version`, publish `CORRECTION_RECEIVED` (dedupe key = document sha256 + fdr), worker resumes at `extract_document` with `execution_version` unchanged (same execution, new attempt) — *document the rule below*.
5.3 Notifications: only via outbox; templates versioned; delivery attempts logged; failures visible to Admin.
5.4 Escalation: timer → `ESCALATED`, exception item for official, notify per policy.

### Recovery semantics (must be implemented exactly)
| Mode | Meaning | Reuses | Reruns | History |
|---|---|---|---|---|
| **Retry** | Same failed operation, same input | input_ref, idempotency key | that node only | new attempt row, parent = failed one |
| **Resume** | Continue after wait/crash from last checkpoint | latest checkpoint | next node onward | continues |
| **Replay** | Re-run from an earlier checkpoint | checkpoint snapshot | that node + downstream | new rows with `replay_of_id`; old preserved |
| **New execution version** | Rule/workflow version changed or case restarted | document + declared data | whole workflow | new `workflow_instance` execution_version |
| **Reprocess after input change** | New document version | new document, old results kept as superseded | extraction → onward | old document's results retained, marked superseded |

---

## Phase 6 — Human Approval & Exception Inbox (Backend)

Steps:
6.1 `human_review` node sets `WAITING_HUMAN`, creates `exception_item` or review task with evidence refs and an AI summary (labelled `AI_RECOMMENDATION`).
6.2 Decision API validates: user role = AICTE Official; case in correct state; user permitted for institution/scope; rationale non-empty; idempotency key; not already decided.
6.3 Write `approval_record`, audit, publish `OFFICIAL_DECISION`, transition, notify institution via outbox.
6.4 Release/refund: **always** requires explicit human approval; agent can only prepare a summary. No bulk approval of release/refund.
6.5 Bulk review allowed only for explicitly listed low-risk actions (e.g., bulk "acknowledge reminder"), each with confirmation and per-item audit.

**Endpoints** in Phase 7 table.

---

## Phase 7 — Workflow Debugger, Node Replay & Recovery API

### Step 7.1 — Node replay safety classification (store in node definition)
| Class | Meaning | Replay rule |
|---|---|---|
| `PURE` | No side effects (extract, validate, summarize) | Replay freely (permission-checked) |
| `IDEMPOTENT_EFFECT` | Effect guarded by idempotency key | Replay allowed; effect suppressed if key already used; UI shows "will not re-send" |
| `NON_IDEMPOTENT_EFFECT` | e.g., a send without provider dedupe | Replay blocked by default; allow only with explicit "send again" flag + reason + confirmation + new idempotency suffix |
| `HUMAN_DECISION` | Approvals | Never replayable; only a new decision can supersede |

### Step 7.2 — Endpoints (all under `/api/v1`, auth required) `[adapt to existing routing]`
| Method & path | Role | Purpose |
|---|---|---|
| GET `/workflows/{fdr_id}` | Official, Admin; Institution (own, redacted) | Instance + graph definition + node statuses |
| GET `/workflows/{id}/executions?node=&status=` | Official, Admin | Execution list |
| GET `/workflows/executions/{exec_id}` | Official, Admin | Inputs/outputs/errors/diagnostics |
| GET `/workflows/{id}/compare?a=&b=` | Official | Diff two executions |
| POST `/workflows/{id}/pause` | Official | body `{reason}` |
| POST `/workflows/{id}/resume` | Official | body `{reason}` |
| POST `/workflows/executions/{exec_id}/retry` | Official | body `{reason, idempotency_key}` |
| POST `/workflows/{id}/replay` | Official | body `{from_checkpoint_id, reason, idempotency_key, acknowledge_side_effects: bool}` |
| POST `/workflows/{id}/new-version` | Official | body `{reason}` |
| GET `/workflows/{id}/stream` | Official | SSE |
| GET `/exceptions?status=&priority=&q=` | Official | Inbox |
| POST `/exceptions/{id}/claim` | Official | |
| POST `/approvals` | Official | `{fdr_id, request_type, decision, rationale, idempotency_key}` |
| GET `/notifications?status=` / GET `/notifications/{id}/attempts` | Official, Admin | |
| GET/PUT `/admin/rules`, POST `/admin/rules/{id}/versions` | Admin | |
| POST `/admin/test-alert` | Admin | |
| GET `/admin/health` / `/admin/failed-jobs` | Admin | |
| POST `/commands/interpret` · POST `/commands/{id}/confirm` · POST `/commands/{id}/cancel` · GET `/commands` · GET `/commands/{id}/stream` | Official (Admin subset) | Phase 9 |
| GET `/ml/predictions?entity=` | Official/Admin | Phase 13 |

**Replay request validation:** (1) authz; (2) instance not COMPLETED/CANCELLED unless policy allows; (3) checkpoint belongs to instance; (4) classify downstream nodes; (5) if any `NON_IDEMPOTENT_EFFECT` downstream and no acknowledgement → `409 SIDE_EFFECT_CONFIRMATION_REQUIRED` with list; (6) no concurrent execution (`409 INSTANCE_BUSY`); (7) idempotency key replay returns original result.

**Error shape (all APIs):**
```json
{"error": {"code": "ILLEGAL_TRANSITION", "message": "...", "details": {}, "request_id": "..."}}
```
Codes: `UNAUTHENTICATED 401`, `FORBIDDEN 403`, `NOT_FOUND 404` (also for cross-institution access), `ILLEGAL_TRANSITION 409`, `INSTANCE_BUSY 409`, `SIDE_EFFECT_CONFIRMATION_REQUIRED 409`, `VALIDATION_ERROR 422`, `RATE_LIMITED 429`.

Each endpoint: writes audit; has unit + integration tests; mutating endpoints accept `Idempotency-Key`.

---

## Phase 8 — Live Updates (SSE)

Steps:
8.1 Postgres `LISTEN/NOTIFY` (or Redis pub/sub if present) → SSE endpoint per instance and per inbox.
8.2 Events: `node.started|succeeded|failed`, `state.changed`, `exception.created`, `approval.recorded`, `command.progress`.
8.3 Client reconnect with `Last-Event-ID`; server replays from `workflow_event` / execution table.
8.4 Authorization checked at connect and per-event scope filter (institution isolation).
8.5 Fallback: polling every N seconds if SSE blocked.

---

## Phase 9 — Natural-Language Command Center

### Step 9.1 — Pipeline
`text → LLM intent parse (JSON schema) → server-side entity resolution → authz/scope check → policy validation → plan preview → (confirmation if required) → allowlisted tool execution → progress stream → summary → audit`

### Step 9.2 — Action schema
```json
{
  "intent": "FIND_MATURING | RECHECK_DOCUMENT | LIST_BY_STATE | PREPARE_REMINDERS | LIST_OVERDUE | PAUSE_CASE | RETRY_NODE | LIST_AWAITING_MY_APPROVAL | EXPLAIN_BLOCKED | SUMMARIZE_FAILED_NOTIFICATIONS",
  "args": {"fdr_ref": "FDR-1024", "days": 30},
  "confidence": 0.0
}
```
Model-supplied `fdr_ref` is a **string to look up**, never a trusted DB id. Server resolves via query scoped to the user; ambiguous/none → ask the user.

### Step 9.3 — Tool allowlist
| Tool | Type | Confirmation |
|---|---|---|
| `find_fdrs(filter)` | read | no |
| `list_cases(state)` | read | no |
| `explain_case_status(fdr)` | read | no |
| `summarize_failed_notifications(range)` | read | no |
| `recheck_document(fdr)` | mutating (PURE node) | yes if >1 case |
| `retry_node(exec_id)` | mutating | yes |
| `pause_case(fdr)` / `resume_case` | mutating | yes |
| `prepare_reminders(filter)` | creates *drafts* | yes; sending requires separate confirm |
| `escalate_cases(filter)` | mutating | yes; bulk preview mandatory |
| **No tool** for: raw SQL, role/permission changes, release/refund approval, deleting audit, config of security settings |

Each tool: typed Pydantic args, `required_role`, `scope_check(user, args)`, `max_batch_size`, `is_bulk`, dry-run preview function.

### Step 9.4 — Preview & execution
- `POST /commands/interpret` returns `{command_id, plan: [{step, tool, resolved_targets[], effect_summary, requires_confirmation}], warnings[]}`; stores `plan_hash`.
- `POST /commands/{id}/confirm` must send matching `plan_hash`; any drift (state changed) → re-plan.
- Execution runs as a background job; progress via SSE; cancel stops before next step; completed steps are not rolled back automatically (state this in UI).
- Prompt-injection: command text and any retrieved case text go in separate delimited blocks; tool outputs never re-enter as instructions.

**Tests:** cross-institution reference rejected; model returns unknown tool → rejected; bulk without confirm → rejected; "approve release for all" → refused/unsupported; plan_hash mismatch → 409.

---

## Phase 10 — Institution Assistance Agent (Agent A)

Steps:
10.1 Endpoint: `POST /institution/assistant/messages` — context built **server-side** from the caller's own cases only.
10.2 Tools (read-mostly, institution-scoped): `get_case_state`, `list_required_actions`, `explain_discrepancy`, `get_deadlines`, `get_renewal_requirements`, `get_release_requirements`.
10.3 Prefill flow: upload → extraction → form prefilled with per-field confidence badge → institution must **confirm/edit** each field before submit; unconfirmed low-confidence fields highlighted; field provenance stored (`EXTRACTED` vs `DECLARED`).
10.4 "Next action" derived from `lifecycle_state` via a deterministic mapping table; LLM only rephrases.
10.5 Guardrails: no authenticity claims ("this FDR is genuine"); no invented values; say "not found in document" when missing.
10.6 Optional DAGMM (Phase 13) surfaces only as "unusual pattern — review suggested", never rejection.

**Acceptance:** agent cannot return data from another institution in adversarial tests; answers about next action match state table 100% on test cases.

---

## Phase 11 — Admin Operations Agent (Agent C) & Monitoring

Steps:
11.1 Metrics collector (Postgres queries/materialized views): failed jobs, retries, dead letters, queue age, workflow duration per node, notification failure rate, stuck cases (no progress > SLA).
11.2 Threshold rules first (deterministic): e.g., failure rate > X% over Y minutes, instance in RUNNING with expired lease, outbox DEAD count > 0.
11.3 Agent tools (read-only + safe actions): `get_failed_jobs`, `get_stuck_cases`, `get_delivery_failures`, `generate_health_report`, `recommend_recovery` ; safe actions limited to *requeue failed job* / *send test alert* with confirmation.
11.4 **Forbidden:** change permissions, security settings, delete data.
11.5 Optional BOCPD overlay (Phase 13) compared against thresholds.

---

## Phase 12 — Frontend (per role)

> Verify framework/router first (`app/` vs `pages/`). Routes below are **proposals**; map to the existing structure.

### Common requirements for every screen
Loading skeleton · empty state with guidance · error state with retry + request_id · success toast · keyboard navigable · labelled controls · colour-independent status (icon+text) · responsive (stack panes <768px) · live update via SSE with polling fallback · permission-gated actions (UI hiding is cosmetic; backend enforces).

### 12.1 Institution
| Route | Objective | Key components / APIs | Acceptance |
|---|---|---|---|
| `/institution` | Overview metrics, deadlines | cards; GET summary | numbers match DB for seeded data |
| `/institution/fdrs/new` | Submit w/ prefill | uploader, extracted-field review form, confidence badges | cannot submit with unconfirmed required field |
| `/institution/fdrs` & `/[id]` | Track, view observations, resubmit | status timeline, document preview, correction form | resubmission resumes workflow |
| `/institution/renewals`, `/releases` | Renewal & release requests | request forms + status | duplicate submit prevented |
| `/institution/notifications` | Notification center | list + read state | |
| Assistant panel (drawer) | Guidance | chat + next-action card | no cross-tenant data |

### 12.2 AICTE Official
| Route | Objective | Components |
|---|---|---|
| `/official/queue` | Verification queue | filters, priority, due date |
| `/official/review/[id]` | Split-view PDF + evidence | PDF viewer, discrepancy panel, source highlights, decision bar |
| `/official/control-room` | Overview of running/failed/waiting | counters, live list |
| `/official/workflows/[id]` | Live graph + debugger | `@xyflow/react` graph; node drawer (inputs/outputs/error/duration/rule+workflow version); timeline; compare executions; Retry / Replay / Pause / Resume with confirmation modal listing side effects |
| `/official/exceptions` | Exception inbox | table, claim, recommended action, approve/reject/request-correction/escalate |
| `/official/approvals` | Human approval & release/refund queue | per-case decision, no bulk for release |
| `/official/command` | Command Center | input, plan preview, confirm, progress stream, history |
| `/official/audit` | Case history & audit viewer | filter by case/actor/action |

Debugger UI state machine: `idle → nodeSelected → (viewing) → actionChosen → confirming (side-effect list) → submitting → success | error(409 conflict → refresh)`. Read-only inspection visually separated from state-changing buttons (different panel/colour + lock icon when unauthorized).

### 12.3 Admin
`/admin/users`, `/admin/institutions`, `/admin/roles`, `/admin/dashboard`, `/admin/rules` (versioned config, diff view), `/admin/alerts` (test alert + delivery log), `/admin/jobs` (failed jobs, dead letters), `/admin/health` (anomaly timeline), `/admin/audit`, `/admin/ops-agent`.

---

## Phase 13 — Optional ML (Data-Dependent; Gate Each One)

**Gate 0 (all models):** write target, metrics, acceptance criteria *before* training; confirm real data volume. If insufficient → do not train; keep the deterministic fallback. Synthetic data must be labelled `is_synthetic=true` in registry and UI; never report synthetic metrics as real.

| Model | Use | Prereqs | Evaluate against | Fallback |
|---|---|---|---|---|
| DAGMM (Institution) | Unusual structured FDR record patterns | Enough clean historical records; feature list (amount, tenure, bank, gaps, filing times); missing-value policy | Isolation Forest / z-score baseline; precision@k via officer review; score calibration | Deterministic rules |
| DeepHit (Official) | Time-to-resolution / deadline risk | Chronological timestamps; define event + censoring; no target leakage | Chronological split; C-index/time-dependent AUC; calibration; vs. Cox/rule-based priority | Rule-based priority |
| BOCPD (Admin) | Change-points in ops metrics | Metric series with baseline; irregular sampling handling | False-positive rate, detection delay vs. thresholds | Threshold monitoring |

Pipeline: `data extract → feature build (versioned) → train (seeded) → evaluate → register (ml_model_version) → batch/online inference service → store ml_prediction → display as "recommendation"`. Reproducibility: pin seed, library versions, data hash. Inference never feeds an authorization decision.

---

## Phase 14 — Security & Reliability Hardening

### Threat model summary
| Threat | Mitigation |
|---|---|
| Cross-institution data access (IDOR) | Server-side scoping on every query; 404 not 403; automated isolation tests |
| Privilege escalation via agent | Tools allowlisted; agent has no permission-management tool; actor = authenticated user |
| Prompt injection via PDF | Doc text = data; JSON-schema outputs; no tools in extraction; output validation |
| LLM hallucinated IDs | Server-side resolution; never trust model-supplied IDs |
| Malicious upload | MIME+magic-byte check, size limit, AV scan if available, store outside web root, signed short-lived URLs |
| Replay / duplicate requests | Idempotency keys; unique constraints; dedupe_key on events |
| Audit tampering | Append-only role grants; hash chain; periodic export |
| Secret leakage | Env/secret manager; never log prompts with PII; redact diagnostics |
| Brute force / abuse | Rate limits on auth, commands, LLM endpoints |
| Bulk accidental action | Plan preview, `max_batch_size`, confirmation, plan_hash |
| Data loss | Backups, tested restore, retention policy `[needs policy owner]` |

Also: session/JWT expiry & rotation, CSRF for cookie auth, structured logs with `request_id`, error tracking, incident runbook.
Do **not** claim regulatory compliance or production readiness without evidence.

---

## Phase 15 — Testing Plan

### Unit
State transitions (exhaustive table) · permission matrix · date/maturity/reminder offsets (incl. leap year, IST boundary) · idempotency-key generation · command schema validation · validation rules · ML preprocessing.

### Integration
| Case | Expected |
|---|---|
| Submit → instance + event created atomically | ✔ |
| OCR output with mismatch → discrepancy → correction notification | exactly 1 notification |
| Correction upload → workflow resumes | new document_version, old results retained |
| Worker retry of notification | no duplicate send |
| Official approval → workflow continues | audit + approval_record |
| Command executes with authorization; cross-tenant ref rejected | ✔ |
| Replay PURE node | new execution, original intact |
| Replay side-effect node without ack | 409 |

### End-to-end
Full lifecycle · discrepancy/correction · renewal · release/refund · failed-node recovery · **kill worker mid-run** · notification provider outage + recovery · institution isolation.

### Failure injection
Kill worker after outbox send before mark-sent; DB deadlock/serialization failure; LLM timeout/garbage JSON; Redis restart; duplicate SSE/event delivery.

### ML tests
Leakage check; baseline comparison; chronological split; calibration; synthetic/real separation; reproducible retraining.

### Acceptance targets (proposed — require validation, not achieved results)
- 0 duplicate notifications across failure-injection suite.
- 0 cross-institution leaks in isolation suite.
- Worker crash recovery completes ≤ configured lease + retry time.
- 100% of mutating endpoints produce audit events.
- 100% of command tool calls pass server-side authz check.

---

## Phase 16 — Deployment

**Services:** web (Next.js) · api (FastAPI) · worker · scheduler (single instance or leader-locked) · outbox dispatcher (can run in worker) · Postgres · Redis (if Celery) · object storage.

**Env vars (names are suggestions `[VERIFY existing]`):** `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`/auth vars, `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `STORAGE_*`, `NOTIFY_*` (SMTP/SMS), `WORKER_LEASE_SECONDS`, `MAX_RETRIES`, `SSE_*`, `RULES_DEFAULT_TZ=Asia/Kolkata`, `ENABLE_ML_*` flags, `SENTRY_DSN`.

**Release steps:** backup → run migrations → deploy API → deploy workers (drain old first) → enable scheduler → enable feature flags progressively (workflow engine → debugger → command center → agents → ML).
**Rollback:** feature flags off; workers stopped; down-migrations additive-only so old code still runs; restore from backup if backfill failed.
**Monitoring:** queue depth, oldest-pending age, failed/dead jobs, outbox backlog, LLM latency/errors, SSE connections.

---

## Phase 17 — MVP (Smallest Demo of the USP)

Build in this order (subset of phases above):
1. Phase 1 (minimal tables: instance, node_execution, event, outbox, audit, approval) → Phase 2 → Phase 3 (engine with 5 nodes: extract, validate, request_correction, wait_institution, human_review).
2. Phase 4 using existing OCR.
3. Phase 7 (inspect + retry + replay-PURE only) + Phase 8 (SSE).
4. Phase 6 (single approval flow) .
5. Phase 9 with 4 tools: `find_fdrs`, `list_cases`, `explain_case_status`, `retry_node`.
6. Frontend: workflow graph + node drawer + exception inbox + command box.

**Demo script:**
1. Institution submits FDR with a mismatched amount (seeded PDF).
2. Worker auto-extracts, detects discrepancy, sends one correction notification, pauses.
3. Official opens graph; sees `validate_fields` flagged; inspects evidence.
4. Simulate transient extraction failure on re-upload → node fails → official inspects error → Retry → success.
5. Institution uploads corrected FDR → workflow resumes → READY_FOR_SCRUTINY → human approval.
6. Official types "Show cases waiting for correction" and "Explain why FDR-1024 is blocked" → plan preview → results.
7. Open audit viewer: full trace, no duplicate notifications.

---

## Final Execution Checklist

- [ ] P0 audit report + matrix + ADRs reviewed
- [ ] Open questions answered (below)
- [ ] P1 migrations up/down verified on a data copy
- [ ] P2 audit + outbox duplicate-safe
- [ ] P3 engine survives worker kill test
- [ ] P4 validation + injection tests
- [ ] P5 resume-after-correction works
- [ ] P6 approvals enforce authz
- [ ] P7 debugger APIs + replay safety
- [ ] P8 SSE with isolation
- [ ] P9 Command Center allowlist + confirmation
- [ ] P10–P11 agents scoped & tested
- [ ] P12 UI states & accessibility checked
- [ ] P13 ML gated by data & metrics (or skipped)
- [ ] P14 threat-model controls verified
- [ ] P15 suites green (record real output)
- [ ] P16 staged deploy + rollback rehearsed
- [ ] P17 demo rehearsed end-to-end

### Verification commands (adapt to repo)
```bash
pytest -q                       # backend
npm run lint && npm run test    # frontend
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
docker compose up --build       # full stack smoke
```

### Open Questions to Resolve in Phase 0
1. What are the actual existing roles and statuses in the DB?
2. Is there any real bank-verification integration, or only mock?
3. Which job/scheduler system exists today?
4. Which LLM provider and keys are configured?
5. Is historical FDR data available (volume, quality)? → decides Phase 13.
6. Required SLAs for correction, escalation, and release decisions (policy owner)?
7. Data-retention and legal requirements for documents and audit logs?
8. Notification channels in scope (email/SMS/in-app)?

### Blockers to flag early
No Redis/queue available · no migration tool · no append-only DB permission control · missing institution-scoping in existing queries · no real bank API (verification stays "mock/consistency only").
