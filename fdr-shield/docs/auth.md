# AICTE FDR Portal — Manual Authentication & 3 Separate Logins (Detailed Implementation Guide)

> Companion to `AICTE_FDR_Implementation_Steps.md`. **Do this BEFORE Phase 1 of that file**, because every API, workflow action and dashboard depends on knowing *who* the user is and *which role* they have.
> Stack assumed (change if your repo differs): **FastAPI + SQLAlchemy + Alembic + PostgreSQL** (backend), **Next.js + TypeScript** (frontend). Items marked `[VERIFY]` must be checked against your real repository first.

---

## 1. What We Are Building

| Item | Decision |
|---|---|
| Auth type | Manual: email/username + password (no third-party login) |
| Roles | `INSTITUTION`, `AICTE_OFFICIAL`, `ADMIN` (exactly 3) |
| Login pages | 3 separate portals: `/institution/login`, `/official/login`, `/admin/login` |
| Session | Short-lived access JWT + rotating refresh token, both in **httpOnly cookies** |
| Password hashing | **argon2id** (fallback bcrypt cost ≥ 12) |
| Authorization | Enforced on the **backend** for every request; frontend guards are only cosmetic |
| Data isolation | Institution users can only see their own institution's data |

### Why one `user` table, three login endpoints
- One table keeps password, lockout, reset and audit logic in one place.
- Three endpoints (one per portal) mean an Institution user **cannot** log in through the Official portal, even with a correct password. The endpoint checks that the account's role equals the portal's role.
- Wrong-portal and wrong-password both return the **same generic error** so attackers can't learn which accounts/roles exist.

---

## 2. Who Creates Which Account (Account Lifecycle)

| Role | How the account is created |
|---|---|
| `ADMIN` (first) | Created by a one-time CLI seed script using env vars. No public signup. |
| `ADMIN` (more) | Created by an existing Admin only. |
| `AICTE_OFFICIAL` | Created by Admin → system emails a one-time invite link → official sets own password. **No self-signup.** |
| `INSTITUTION` | Self-registration form → email verification → **Admin approval** (status `PENDING_APPROVAL` → `ACTIVE`). Optionally Admin can also create/invite institution users. |

Account statuses: `PENDING_EMAIL_VERIFY`, `PENDING_APPROVAL`, `ACTIVE`, `LOCKED`, `DISABLED`, `INVITED`.

Only `ACTIVE` accounts can log in.

---

## 3. Database Design

> First check whether your repo already has `users`/`institutions` tables `[VERIFY]`. If yes, **add columns/migrate** instead of creating duplicates.

### 3.1 `institution`
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| name | text NOT NULL | |
| aicte_institution_id | text UNIQUE | official AICTE ID `[VERIFY format]` |
| email, phone, address | text | |
| status | text | ACTIVE / SUSPENDED |
| created_at, updated_at | timestamptz | |

### 3.2 `app_user`
| Field | Type | Constraints / Notes |
|---|---|---|
| id | UUID PK | |
| email | citext UNIQUE NOT NULL | lowercase; login identifier |
| full_name | text NOT NULL | |
| password_hash | text NULL | NULL while `INVITED` |
| role | text NOT NULL | CHECK IN ('INSTITUTION','AICTE_OFFICIAL','ADMIN') |
| institution_id | UUID FK → institution NULL | **REQUIRED when role=INSTITUTION; MUST be NULL otherwise** (CHECK constraint) |
| status | text NOT NULL | see statuses above |
| must_change_password | bool default false | |
| failed_login_count | int default 0 | |
| locked_until | timestamptz NULL | |
| last_login_at | timestamptz NULL | |
| email_verified_at | timestamptz NULL | |
| mfa_enabled | bool default false | optional (Section 11) |
| mfa_secret_enc | text NULL | encrypted TOTP secret |
| created_by | UUID FK app_user NULL | |
| created_at, updated_at | timestamptz | |

Constraints:
```sql
CHECK (
  (role = 'INSTITUTION' AND institution_id IS NOT NULL) OR
  (role <> 'INSTITUTION' AND institution_id IS NULL)
)
```
Indexes: `UNIQUE(email)`, `(role, status)`, `(institution_id)`.

### 3.3 `refresh_token`
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | FK | indexed |
| token_hash | text UNIQUE | SHA-256 of the random token (never store raw) |
| family_id | UUID | all rotated tokens from one login share a family |
| issued_at, expires_at | timestamptz | e.g. 7 days |
| used_at | timestamptz NULL | set on rotation |
| revoked_at | timestamptz NULL | |
| ip, user_agent | text | |

### 3.4 `one_time_token` (invite, email verify, password reset)
id · user_id FK · purpose (`INVITE`/`VERIFY_EMAIL`/`RESET_PASSWORD`) · token_hash UNIQUE · expires_at · used_at · created_at.

### 3.5 `login_attempt` (for rate limiting + forensics)
id · email_attempted · portal · success bool · failure_reason (internal only) · ip · user_agent · created_at. Index `(email_attempted, created_at)`, `(ip, created_at)`.

### 3.6 `audit_event`
Reuse from the main guide (Phase 2). Log: login success/fail, logout, token reuse detected, account created/approved/disabled, role/status change, password change/reset, MFA changes.

### 3.7 Migration
1. Additive Alembic migration. If `users` exists, map old role names → the 3 roles and document unmapped ones (don't silently drop e.g. "Scrutiny Officer"/"Bureau Chief"; decide mapping with owner).
2. Seed script creates the first Admin.
3. Rollback = down-migration; no destructive changes to old tables.

---

## 4. Backend Implementation (Step by Step)

### Step 4.1 — Dependencies
```
argon2-cffi        # password hashing
PyJWT              # JWT (or python-jose)
email-validator
python-multipart
pydantic-settings
slowapi            # rate limiting (or reuse existing / Redis-based)
pyotp              # only if enabling TOTP MFA
```
Justify each in the PR; skip any already present.

### Step 4.2 — Config (env vars)
```
JWT_SECRET=<long random, from secret manager>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=7
COOKIE_SECURE=true            # false only on localhost
COOKIE_SAMESITE=lax           # strict if same-site deployment
COOKIE_DOMAIN=<your domain>
FRONTEND_ORIGIN=https://...
LOGIN_MAX_FAILURES=5
LOCKOUT_MINUTES=15
INITIAL_ADMIN_EMAIL=...
INITIAL_ADMIN_PASSWORD=...    # used once by seed script then removed
```
Never commit secrets; fail startup if `JWT_SECRET` is missing or short.

### Step 4.3 — Password module (`auth/passwords.py`)
```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
ph = PasswordHasher()                # argon2id defaults; tune for your server

def hash_password(p: str) -> str: return ph.hash(p)

def verify_password(hash_: str, p: str) -> bool:
    try: return ph.verify(hash_, p)
    except VerifyMismatchError: return False

def needs_rehash(hash_: str) -> bool: return ph.check_needs_rehash(hash_)
```
Policy (`validate_password_strength`): min 12 chars, not in a common-password list, not equal to email/name; no forced composition rules (length matters more). Reject on weak with a clear 422 message.

**Timing safety:** when the email doesn't exist, still run a dummy `verify_password` against a fixed hash so response time doesn't reveal account existence.

### Step 4.4 — Token module (`auth/tokens.py`)
- **Access JWT** claims: `sub` (user id), `role`, `inst` (institution_id or null), `jti`, `iat`, `exp` (15 min), `typ="access"`. Don't put email/PII in it.
- **Refresh token**: 256-bit random string (`secrets.token_urlsafe(48)`); store only its SHA-256 in `refresh_token`.
- **Rotation:** each `/auth/refresh` marks the presented token `used_at`, issues a new one in the same `family_id`.
- **Reuse detection:** if a token with `used_at` set is presented again → revoke the entire family, audit `TOKEN_REUSE_DETECTED`, force re-login.
- **Role is re-read from DB on refresh** (so a disabled/role-changed user loses access within one access-token lifetime). For immediate effect on sensitive roles, also check `status` on each request (cheap indexed lookup) — recommended for Admin/Official.

### Step 4.5 — Cookies
```python
response.set_cookie("access_token", jwt, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=900, path="/")
response.set_cookie("refresh_token", raw, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=7*86400, path="/api/v1/auth")  # scope refresh cookie
```
Never store tokens in localStorage.
**CSRF:** because cookies are used, add CSRF protection for state-changing requests: double-submit cookie (`csrf_token` readable cookie + `X-CSRF-Token` header compared server-side), or strict `SameSite=Strict` + `Origin` header check. Pick one and test it. Set CORS `allow_origins=[FRONTEND_ORIGIN]` with `allow_credentials=True` (never `*`).

### Step 4.6 — Login service (single shared function)
```python
def authenticate(portal_role: Role, email: str, password: str, ip, ua) -> LoginResult:
    # 1. rate-limit check by ip + email (429 if exceeded)
    # 2. fetch user by email (lowercased)
    # 3. if no user -> dummy verify, record failure, raise GENERIC_INVALID
    # 4. if user.locked_until > now -> raise GENERIC_INVALID (don't reveal lock;
    #    send "locked" email to user once)
    # 5. verify password; on fail: failed_login_count += 1;
    #    if >= LOGIN_MAX_FAILURES -> locked_until = now + LOCKOUT_MINUTES; record; raise GENERIC_INVALID
    # 6. if user.role != portal_role -> record (internal reason WRONG_PORTAL); raise GENERIC_INVALID
    # 7. if user.status != ACTIVE -> raise GENERIC_INVALID  (optionally specific message
    #    for PENDING_APPROVAL on the Institution portal only)
    # 8. success: reset failed count, set last_login_at, rehash if needed,
    #    create refresh family, issue tokens, audit LOGIN_SUCCESS
```
`GENERIC_INVALID` = HTTP 401 `{"error":{"code":"INVALID_CREDENTIALS","message":"Invalid email or password."}}`.

### Step 4.7 — Authorization dependencies (`auth/deps.py`)
```python
def get_current_user(request) -> CurrentUser:
    # read access_token cookie -> verify signature/exp/typ -> load user -> check status==ACTIVE
    # raise 401 if missing/invalid/expired

def require_roles(*roles: Role):
    def dep(user = Depends(get_current_user)):
        if user.role not in roles: raise HTTPException(403)
        return user
    return dep

def scoped_institution_id(user = Depends(get_current_user)) -> UUID | None:
    return user.institution_id if user.role == Role.INSTITUTION else None
```
**Mandatory pattern:** every repository query for institution data must filter by `institution_id` when the caller is an Institution user. Return **404** (not 403) when an institution requests another institution's record. Write a helper `get_fdr_for_user(user, fdr_id)` and forbid raw `session.get(Fdr, id)` in route handlers.

Apply: `Depends(require_roles(Role.AICTE_OFFICIAL))` on all workflow/debugger/command routes; `Depends(require_roles(Role.ADMIN))` on admin routes; institution routes use `require_roles(Role.INSTITUTION)` + scoping.

### Step 4.8 — Auth API endpoints (`/api/v1/auth`)

| Method & path | Who | Request | Success | Errors |
|---|---|---|---|---|
| POST `/auth/institution/login` | public | `{email, password}` | 200 `{user:{id,name,role,institution_id,must_change_password}}` + cookies | 401 INVALID_CREDENTIALS, 429 RATE_LIMITED |
| POST `/auth/official/login` | public | same | same | same |
| POST `/auth/admin/login` | public | same | same | same |
| POST `/auth/refresh` | cookie | — | 200 + new cookies | 401 (reuse/expired) |
| POST `/auth/logout` | authed | — | 204; revokes refresh family; clears cookies | |
| GET `/auth/me` | authed | — | 200 user profile | 401 |
| POST `/auth/change-password` | authed | `{current_password, new_password}` | 204; revokes other sessions | 401, 422 |
| POST `/auth/forgot-password` | public | `{email}` | **always 202** (same response whether or not email exists) | 429 |
| POST `/auth/reset-password` | public | `{token, new_password}` | 204; revokes all sessions | 400 invalid/expired token, 422 |
| POST `/auth/register/institution` | public | `{institution_name, aicte_institution_id, contact_name, email, password}` | 202; sends verify email | 409 (generic), 422, 429 |
| POST `/auth/verify-email` | public | `{token}` | 204 → status `PENDING_APPROVAL` | 400 |
| POST `/auth/accept-invite` | public | `{token, password, full_name?}` | 204 → `ACTIVE` | 400, 422 |

Notes: registration returns the same 202 message even if the email exists (prevents account enumeration); email is sent either way with appropriate content.

### Step 4.9 — Admin user-management endpoints (`/api/v1/admin`, ADMIN only)

| Method & path | Purpose | Rules |
|---|---|---|
| GET `/admin/users?role=&status=&q=` | List/search | paginated |
| POST `/admin/users` | Create Official/Admin/Institution user (sends invite) | validates role↔institution_id rule |
| PATCH `/admin/users/{id}` | Edit name, institution, role | role change audited; **cannot change own role**; cannot remove last active Admin |
| POST `/admin/users/{id}/disable` / `/enable` | Status | revokes all sessions on disable; cannot disable self/last Admin |
| POST `/admin/users/{id}/unlock` | Clear lockout | audited |
| POST `/admin/users/{id}/reset-password` | Send reset email | |
| POST `/admin/users/{id}/revoke-sessions` | Force logout | |
| GET `/admin/registrations?status=PENDING_APPROVAL` | Pending institution signups | |
| POST `/admin/registrations/{id}/approve` / `/reject` | Approve → ACTIVE (+ create/link institution) | `{reason}` required for reject |
| GET/POST/PATCH `/admin/institutions` | Institution CRUD | |

**Rule:** agents/LLM tools must never call these endpoints (matches the main guide's rule that agents cannot change permissions).

### Step 4.10 — Seed script
`python -m app.cli create_admin` reads `INITIAL_ADMIN_EMAIL/PASSWORD`, creates the Admin if none exists, sets `must_change_password=true`. Idempotent. Document: remove the env password after first run.

### Step 4.11 — Rate limiting & lockout
- Per IP: e.g., 20 login attempts / 10 min. Per email: 10 / 10 min. Registration & forgot-password: 5 / hour / IP. (Proposed values — tune.)
- Account lockout after 5 consecutive failures for 15 minutes; Admin can unlock.
- Use Redis for counters if available; otherwise DB `login_attempt` counts.

### Step 4.12 — Audit events to emit
`LOGIN_SUCCESS`, `LOGIN_FAILURE`, `ACCOUNT_LOCKED`, `LOGOUT`, `TOKEN_REUSE_DETECTED`, `PASSWORD_CHANGED`, `PASSWORD_RESET_REQUESTED/COMPLETED`, `USER_CREATED`, `USER_INVITED`, `USER_APPROVED/REJECTED`, `USER_DISABLED/ENABLED`, `ROLE_CHANGED`, `SESSIONS_REVOKED`, `MFA_ENABLED/DISABLED`. Never log passwords, tokens or full reset links.

### Step 4.13 — Email templates needed
Verify email · Invite · Password reset · Account approved/rejected · Lockout notice · Password changed notice. Links point to frontend routes with the raw one-time token; tokens expire (invite 72h, verify 24h, reset 30 min), single-use.

---

## 5. Frontend Implementation (Step by Step)

### Step 5.1 — Routes

| Route | Purpose |
|---|---|
| `/login` | Portal chooser: 3 cards (Institution / AICTE Official / Admin) |
| `/institution/login` | Institution login + links: Register, Forgot password |
| `/institution/register` | Registration form |
| `/official/login` | Official login (no signup link) |
| `/admin/login` | Admin login (no signup link) |
| `/verify-email?token=` | Email verification result |
| `/accept-invite?token=` | Set password for invited user |
| `/forgot-password`, `/reset-password?token=` | Reset flow |
| `/account/change-password` | Authenticated change (also forced on first login) |
| `/institution/*`, `/official/*`, `/admin/*` | Protected dashboards |
| `/unauthorized` | Shown on 403/role mismatch |

### Step 5.2 — Login page requirements (each portal)
- Fields: email, password (show/hide toggle), submit button with loading state.
- Visible portal title + role-specific styling so users know where they are.
- Inline error: generic "Invalid email or password." Rate-limit error: "Too many attempts. Try again later."
- Pending-approval message only on Institution portal if backend returns it.
- If `must_change_password` → redirect to `/account/change-password` before dashboard.
- Accessibility: labelled inputs, `aria-live` error region, focus on first error, full keyboard use.
- Responsive: single column, max width ~400px.
- Redirect after login: Institution → `/institution`, Official → `/official/queue`, Admin → `/admin/dashboard`.

### Step 5.3 — Auth state
- `AuthProvider` calls `GET /auth/me` on load; stores `{user, status: loading|authed|anon}` in memory (not localStorage).
- API client: `fetch(..., {credentials:"include"})`, adds `X-CSRF-Token`; on 401 → single-flight `POST /auth/refresh` then retry once; if refresh fails → clear state and redirect to that role's login page with `?expired=1`.
- Logout button calls `/auth/logout`, then redirects to the portal's login.

### Step 5.4 — Route protection
- Next.js `middleware.ts`: check presence of access/refresh cookie for `/institution/*`, `/official/*`, `/admin/*`; redirect to the matching login if absent. (Presence check only — signature verification happens on the backend.)
- Layout-level guard per area: after `/auth/me`, if `user.role` ≠ area's role → `/unauthorized`.
- Hide nav/actions the role can't use — but remember the backend is the real enforcement.

### Step 5.5 — Admin screens (user management)
`/admin/users` (table, filters, create/invite dialog, disable/enable, unlock, reset password, revoke sessions), `/admin/registrations` (approve/reject with reason), `/admin/institutions`. Confirmation dialogs for disable/role change; show audit snippet per user.

### Step 5.6 — UX states for every screen
Loading skeleton · empty state · error + retry · success toast · disabled submit while pending · session-expired banner.

---

## 6. Role → Permission Matrix (starting point)

| Capability | INSTITUTION | AICTE_OFFICIAL | ADMIN |
|---|---|---|---|
| Submit/view **own** FDRs | ✔ (own only) | — | — |
| View all FDRs | ✘ | ✔ | ✔ (stats/ops) |
| Verification/scrutiny decisions | ✘ | ✔ | ✘ |
| Release/refund decision | ✘ | ✔ (authorized) | ✘ |
| Workflow debugger / replay | ✘ | ✔ | read-only health |
| Command Center | ✘ | ✔ | limited ops commands |
| Manage users/roles | ✘ | ✘ | ✔ |
| Reminder/escalation config | ✘ | ✘ | ✔ |
| Audit viewer | own case history | case audit | system audit |

Confirm against business owner; adjust before coding.

---

## 7. Implementation Order (Task List)

1. **A1** Audit existing auth/users `[VERIFY]`; decide migrate vs create.
2. **A2** Alembic migration: `institution`, `app_user`, `refresh_token`, `one_time_token`, `login_attempt`.
3. **A3** Config + secrets validation.
4. **A4** `passwords.py` + unit tests.
5. **A5** `tokens.py` (JWT, refresh rotation, reuse detection) + unit tests.
6. **A6** `deps.py` (`get_current_user`, `require_roles`, institution scoping) + unit tests.
7. **A7** Login service + 3 portal endpoints + lockout + rate limit.
8. **A8** refresh/logout/me/change-password.
9. **A9** Email service + invite/verify/forgot/reset flows.
10. **A10** Institution registration + admin approval.
11. **A11** Admin user-management endpoints + safeguards (last admin, self-demotion).
12. **A12** Apply `require_roles` + institution scoping to **all existing routes** (inventory every route; none left unprotected).
13. **A13** Seed script.
14. **A14** Frontend: API client, AuthProvider, middleware, 3 login pages, register, reset flows.
15. **A15** Frontend: admin user management screens.
16. **A16** Security tests + E2E tests (Section 8).
17. **A17** Documentation + env var list + rollback notes.

---

## 8. Testing

### Unit
Hash/verify/rehash · password policy · JWT expiry/tampering/wrong type · refresh rotation · reuse detection revokes family · role↔institution CHECK constraint · lockout counter · token single-use & expiry.

### Integration
| Test | Expected |
|---|---|
| Correct creds, correct portal | 200 + cookies |
| Correct creds, **wrong portal** | 401 generic |
| Wrong password ×5 | lockout; correct password still rejected until expiry |
| Unknown email vs wrong password | identical response body + similar timing |
| Disabled user mid-session | rejected within access-token lifetime (immediate for Admin/Official if per-request status check on) |
| Reused refresh token | 401 + whole family revoked |
| Forgot password for unknown email | 202, same as known |
| Reset token reuse/expiry | 400 |
| Institution A requests Institution B's FDR | 404 |
| Institution user calls `/official/*` or `/admin/*` | 403 |
| Official calls `/admin/users` | 403 |
| Admin disables last Admin / self | rejected |
| CSRF: POST without header | 403 |
| Every existing route | has an auth dependency (automated route-introspection test fails if any is public unintentionally) |

### E2E (Playwright/Cypress)
Register institution → verify email → admin approves → login → logout · Admin invites official → accept invite → login · Session expiry → refresh → continue · Forced password change on first login · Forgot/reset flow.

### Proposed acceptance targets (to be validated, not achieved results)
- 0 unauthenticated access to protected routes in the route-introspection test.
- 0 cross-institution reads in isolation tests.
- No endpoint reveals whether an email exists.
- All auth events appear in audit log.

---

## 9. Security Checklist

- [ ] argon2id hashing; no plaintext/reversible passwords anywhere
- [ ] Tokens only in httpOnly, Secure cookies; none in localStorage/URL
- [ ] Refresh tokens hashed at rest, rotated, reuse-detected
- [ ] CSRF protection verified
- [ ] CORS locked to your frontend origin
- [ ] Generic errors on login/reset/register
- [ ] Rate limiting + lockout active
- [ ] Reset/invite/verify tokens: random, hashed, expiring, single-use
- [ ] HTTPS enforced in production; HSTS
- [ ] Secrets in env/secret manager; startup fails if missing
- [ ] No passwords/tokens in logs
- [ ] Backend authorization on **every** route; institution scoping in every query
- [ ] Last-Admin and self-demotion protections
- [ ] Audit trail for all auth/admin events
- [ ] Agents/LLM tools have **no** access to auth/admin endpoints

---

## 10. Hackathon-Fast Path (if time is short)

Minimum viable auth that is still safe:
1. `app_user` + `institution` tables, seed Admin via script.
2. argon2 hashing, access JWT in httpOnly cookie (skip refresh rotation initially; use 1-hour access token).
3. Three login endpoints + `require_roles` + institution scoping on all routes.
4. Admin creates Official and Institution users (skip self-registration, email verification, forgot-password).
5. Three login pages + middleware guard + logout.
Add refresh rotation, registration/approval and reset flows afterwards.

---

## 11. Optional Enhancements (not required)

- TOTP MFA (pyotp) for Official and Admin accounts; recovery codes; Admin can reset MFA with audit.
- Active-session list with "log out other devices".
- IP allow-listing for Admin portal.
- Password breach-list check (k-anonymity API) — only if outbound network allowed.
- Idle-timeout warning modal in the frontend.

---

## 12. Open Questions to Resolve First

1. Does your repo already have any login/users tables or a mock login? Keep or replace?
2. Are there existing roles beyond the three (e.g., Scrutiny Officer, Bureau Chief)? How should they map?
3. Is email sending available (SMTP/provider)? If not, invites/resets need a manual fallback for the demo.
4. Is the frontend and backend on the same domain (affects cookie `SameSite` and CSRF choice)?
5. Should institutions self-register, or will Admin pre-create all institution accounts?
6. Is MFA required for Official/Admin?
7. Is Redis available for rate limiting?
