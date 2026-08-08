# Joblign Auto-Apply — Requirements Specification

**Status:** Draft v0.1
**Owner:** Patrick Ronning
**Last updated:** 2025-01-XX

## Context

Joblign today parses job postings, generates tailored resumes and cover letters,
scores them with ATS + industry-panel agents, and tracks applications through a
pipeline stage. It does **not** submit applications to external job boards.

This spec defines a new capability: **assisted auto-apply**. The user (Patrick)
provides a target job URL in Joblign. A browser-automation sidecar
(headless Playwright Chromium, provisioned as a sibling service to the existing
URL fetcher in `my-stack`) opens the application form, parses each field,
drafts a payload from the user's stored profile + generated artifacts, fills the
form, and **halts at the final submit button**. The user reviews the staged
form in Joblign, then either approves (sidecar clicks submit) or rejects
(form state is preserved for inspection).

**v1 scope:** assisted mode only (no autonomous submission). Full job-board
coverage via LLM-driven per-form interpretation (no per-board hardcoding).
Headless session ownership; user owns credentials via on-demand viewport
streaming during login.

---

## User Requirements (UR)

### UR-1: Assisted Application Submission
**As** Patrick (job applicant using Joblign)
**I want to** trigger an assisted auto-apply for a saved job posting
**So that** I can have the sidecar fill out the external job-board form with my
profile data and generated artifacts, review what it produced, and approve
submission with one click.

**Acceptance:** Triggering auto-apply on a job results in a filled form
(visible to the user) that is **not yet submitted** until explicit approval.

### UR-2: Pre-Fill Personal & Employment Data
**As** Patrick
**I want to** store a comprehensive profile (contact info, work auth,
experience summary, education entries, work history entries, links, salary
expectations) in Joblign
**So that** the sidecar can answer every structured form field without
re-prompting me on each application.

**Acceptance:** Every profile field listed in FR-2 is editable in the Joblign
UI, persisted to the database, and made available to the sidecar at fill time.

### UR-3: Long-Tail Question Library
**As** Patrick
**I want to** maintain a Q&A bank of common screening questions and my answers
**So that** the LLM can match each free-text question on a form to the most
relevant stored answer.

**Acceptance:** I can add, edit, delete Q&A pairs; the sidecar can retrieve the
top-N best matches by question text per form.

### UR-4: Pre-Submit Review (The Approval Gate)
**As** Patrick
**I want to** see exactly what the sidecar will submit — both as a structured
field-by-field report and as per-field screenshots of the actual filled form
**So that** I can confidently approve, reject, or request a revision.

**Acceptance:** A review screen shows (a) every form field + the value the
sidecar will enter, (b) a per-field screenshot of the filled state, and (c) any
warnings (required fields left blank, validation errors detected). The submit
button is disabled until the review screen has been viewed.

### UR-5: One-Click Submit Approval
**As** Patrick
**I want to** click "Approve & Submit" on the review screen
**So that** the sidecar performs the final click and Joblign records the
application as submitted.

**Acceptance:** Approval triggers a single submission call to the sidecar; on
success the job's stage moves to "Applied" with timestamp and a submission
record (URL submitted to, confirmation text if captured). On failure, stage is
unchanged and a failure report is saved.

### UR-6: Resume + Cover Letter Auto-Upload
**As** Patrick
**I want** the generated resume DOCX and cover letter text for the current job
to be automatically uploaded to file fields on the application form
**So that** I don't have to manually find and attach the right files.

**Acceptance:** When the sidecar detects a file-upload field labeled
resume/CV/cover letter, it uploads the appropriate generated artifact (resume
DOCX for resume/CV fields, PDF-rendered cover letter for cover letter fields).
Filename is preserved (e.g., `Patrick_Ronning_Resume.pdf`).

### UR-7: Manual Login Recovery
**As** Patrick
**I want** the sidecar to pause and let me log in manually when it hits a
login wall
**So that** I keep ownership of my credentials without the sidecar needing to
store passwords.

**Acceptance:** When the sidecar detects a login wall (e.g., LinkedIn auth
screen), it streams its viewport to Joblign in real-time, displays a
"Manual Login Required" prompt with the live stream + an input form for
credential entry, and resumes once it sees the authenticated post-login state.

### UR-8: Smart Failure Recovery
**As** Patrick
**I want** the sidecar to attempt intelligent recovery when it hits an
unexpected UI state
**So that** flaky forms don't require my intervention on every application.

**Acceptance:** On action failure, the sidecar retries once with a short
backoff. On second failure, it captures the current DOM + screenshot and asks
an LLM for a recovery strategy. Up to 3 total attempts; after that, it halts
with a "Manual Recovery Required" state.

### UR-9: Submission Audit Trail
**As** Patrick
**I want** every application attempt to leave a complete audit trail
**So that** I can debug failures, prove what was submitted, and re-run with
corrections.

**Acceptance:** Each application attempt records: target URL, timestamp,
sidecar session ID, per-field filled values, per-field screenshots,
LLM-decision log, final submission result (success/failure), and any
employer-side confirmation text/number captured.

### UR-10: Form Rejection & Manual Completion
**As** Patrick
**I want** to be able to reject the sidecar's staged form and either retry
with corrections or take over manually
**So that** I'm never locked out of completing an application myself.

**Acceptance:** A "Reject" button on the review screen returns the job to
"draft" state with the sidecar session preserved for inspection. A "Take Over
Manually" button returns the job to "saved" stage and shows me the live
sidecar viewport so I can finish the form myself.

---

## Functional Requirements (FR)

### FR-1: Profile Management
**Derived from:** UR-2

The system shall provide CRUD operations for a per-user profile containing:

| Field | Type | Notes |
|---|---|---|
| `first_name`, `last_name` | string | required |
| `email` | string | required, validated |
| `phone` | string | E.164 or free-form |
| `address_line1`, `address_line2` | string | optional |
| `city`, `state`, `postal_code`, `country` | string | |
| `linkedin_url` | string | URL-validated |
| `github_url`, `portfolio_url` | string | optional, URL-validated |
| `work_authorization_status` | enum | `authorized`, `needs_sponsorship`, `citizen`, `permanent_resident`, `other` |
| `years_experience_total` | integer | |
| `salary_expectation_min`, `salary_expectation_max` | integer | |
| `salary_expectation_currency` | string | ISO currency |
| `willing_to_relocate` | boolean | |
| `notice_period_days` | integer | |
| `education` | array of `{school, degree, field, start_year, end_year, gpa?}` | |
| `work_history` | array of `{company, title, start_date, end_date, location, description}` | |
| `custom_fields` | JSON | escape hatch for board-specific structured data |

All fields exposed via REST endpoints:
- `GET /api/profile`
- `PUT /api/profile` (upsert)
- `POST /api/profile/education`
- `DELETE /api/profile/education/{id}`
- `POST /api/profile/work-history`
- `DELETE /api/profile/work-history/{id}`

### FR-2: Q&A Library Management
**Derived from:** UR-3

The system shall provide CRUD for a per-user Q&A bank:
- `GET /api/qa?query={text}&limit={n}` — semantic-or-text match
- `POST /api/qa` — create `{question, answer, tags?, use_count?}`
- `PUT /api/qa/{id}` — update
- `DELETE /api/qa/{id}` — delete

Matching for retrieval: text similarity first (FTS5), with LLM-based semantic
fallback for paraphrased matches. Top-N results returned, default N=3.

### FR-3: Auto-Apply Trigger & State Machine
**Derived from:** UR-1, UR-4, UR-5

A new `ApplicationAttempt` entity tracks each run:

```
state transitions:
  pending → preparing → logging_in → parsing_form → filling_form
         → staged → approved → submitting → submitted
  any state → failed (with reason)
  staged → rejected (user rejected; session preserved)
  staged → manual_takeover (user takes over)
```

Endpoints:
- `POST /api/jobs/{job_id}/auto-apply` — kicks off a new `ApplicationAttempt`,
  returns `attempt_id` and initial state
- `GET /api/jobs/{job_id}/auto-apply/status` — current state + sidecar
  session info + progress
- `GET /api/jobs/{job_id}/auto-apply/{attempt_id}` — full attempt details
  (field report, screenshots)
- `POST /api/jobs/{job_id}/auto-apply/{attempt_id}/approve` — approval gate
- `POST /api/jobs/{job_id}/auto-apply/{attempt_id}/reject` — reject
- `POST /api/jobs/{job_id}/auto-apply/{attempt_id}/takeover` — manual mode

### FR-4: Sidecar Communication Protocol
**Derived from:** UR-1, UR-7, UR-8, UR-10

The Joblign backend shall communicate with the auto-apply sidecar via an
internal HTTP/WebSocket protocol (sidecar lives on the `proxy` Docker network,
reachable as `http://auto-apply:8081` by service name).

Sidecar endpoints (consumed by Joblign):
- `POST /sessions` — create a new browser session, returns `session_id`
- `GET /sessions/{id}` — session state (current URL, page title, login status)
- `GET /sessions/{id}/stream` — WebSocket, streams viewport frames + events
- `POST /sessions/{id}/login-credentials` — submits user-entered creds during
  manual login flow (input via Joblign UI from viewport stream)
- `POST /sessions/{id}/parse-form` — captures DOM, returns parsed field report
- `POST /sessions/{id}/fill-form` — accepts payload `{field_id → value}`,
  returns per-field fill results + screenshots
- `POST /sessions/{id}/approve-and-submit` — single-click final submission
- `POST /sessions/{id}/abort` — closes the session, releases browser
- `GET /sessions/{id}/artifacts` — returns collected screenshots + DOM
  snapshots for the attempt

All sidecar endpoints are internal-only (no Traefik labels, `proxy` network
only).

### FR-5: LLM-Driven Form Interpretation
**Derived from:** UR-1

The sidecar shall, for each form field detected on the page, send the field's
DOM context (label, name, type, placeholder, surrounding text, options) to an
LLM and receive a decision:
- **Field type** (text, email, tel, select, file, checkbox, radio, textarea, date)
- **Semantic intent** (e.g., "phone number", "first name", "resume upload",
  "work authorization status")
- **Confidence** (0-1)
- **Proposed value** (looked up from profile / Q&A bank / generated artifacts)

Fields with confidence < 0.7 are surfaced in the review screen as
"Needs your input" rather than auto-filled.

### FR-6: Manual Login Streaming UI
**Derived from:** UR-7

When the sidecar detects a login wall (heuristics: URL matches known auth
domains, page contains password input, "Sign In" / "Log In" / "Continue with
Google" buttons):
1. Sidecar opens a WebSocket to Joblign
2. Joblign backend proxies frames to the user's browser via its own WebSocket
   to the Joblign frontend
3. Joblign frontend shows a modal: live viewport stream + credential input
   fields
4. User types creds into the modal; Joblign forwards keystrokes to sidecar,
   which types them into the actual page
5. Sidecar monitors for post-login state (URL change + auth cookie presence)
   and auto-resumes

Login credentials are **never persisted** by Joblign or the sidecar.

### FR-7: Smart Retry with LLM Diagnosis
**Derived from:** UR-8

On any action failure (click, type, upload, select):
1. Retry once with 500ms-2s exponential backoff
2. On second failure, capture current DOM + screenshot, send to LLM with prompt:
   "The previous action failed. DOM: [...]. Screenshot: [base64]. Propose a
   recovery strategy (next action to try, or abort)."
3. Execute LLM's proposed action if confidence ≥ 0.5
4. Repeat up to 3 total attempts
5. After 3 failures: capture final state, halt session, surface
   "Manual Recovery Required" in Joblign

### FR-8: Per-Field Screenshots + Field Report
**Derived from:** UR-4, UR-9

For each filled field, the sidecar captures:
- Full-viewport PNG screenshot after the fill
- Cropped screenshot of just the field + label (DOM bbox-based)
- DOM snippet (the rendered HTML of the field + its label)
- The value entered
- Timestamp
- LLM confidence + reasoning

These are stored in the `ApplicationAttempt.screenshots` (JSON array) and
`ApplicationAttempt.field_report` (JSON) fields.

### FR-9: Submission Confirmation Capture
**Derived from:** UR-5, UR-9

After sidecar clicks the final submit button, it waits up to 30 seconds for a
confirmation state (heuristics: URL change to a "thank you" / "application
received" / confirmation-number-bearing page; presence of confirmation text).
Captured:
- Confirmation URL (final page URL)
- Confirmation text (snippet, first 1000 chars)
- Confirmation number / reference ID if regex-matchable
- Final screenshot
- Network response (HTTP status + headers of POST to application endpoint,
  redacted of credentials)

If no confirmation state detected within 30s, the attempt is marked
`submitted_pending_confirmation` (not `submitted`) and surfaced for manual
verification.

### FR-10: Audit Trail & History
**Derived from:** UR-9

Every `ApplicationAttempt` is immutable after completion. Failed/rejected
attempts are preserved, not deleted. The Job detail view shows attempt
history: timeline of attempts, last successful submission, screenshots gallery.

### FR-11: Re-Run with Corrections
**Derived from:** UR-10

A new auto-apply attempt can be initiated against a job even if a previous
attempt exists. Each attempt is independent; the most recent successful
attempt's `submitted_at` is what advances the job stage to "Applied".

---

## Technical Requirements (TR)

### TR-1: Sidecar Service Architecture
- **Runtime:** Python 3.11, FastAPI (parity with Joblign backend)
- **Browser engine:** Playwright + Chromium (headless, persistent profile dir)
- **Container:** sibling to the existing `jobapp-fetcher` in `my-stack`, new
  service name `auto-apply`
- **Network:** `proxy` Docker network only; no Traefik labels
- **Resources:** 1GB mem_limit, 1 CPU (browser instances are heavy)
- **Security posture:** read-only root fs, tmpfs `/tmp`, no-new-privileges,
  all-caps dropped — same as `jobapp-fetcher`
- **Persistent volume:** `/data/sessions` (browser profiles, session state)
- **Health endpoint:** `GET /healthz` on port 8081

### TR-2: Sidecar ↔ Joblign Auth
- Internal mTLS OR shared HMAC token in `Authorization: Bearer` header
- Token sourced from Vault, injected via deploy script envsubst
- Joblign backend uses `httpx.AsyncClient` with token pre-set
- Sidecar rejects any request without valid token

### TR-3: Viewport Streaming Protocol
- WebSocket from sidecar → Joblign backend → frontend
- Frame rate: 5 fps at 720p during login flow (bandwidth-bounded)
- Frame format: JPEG quality 70, max 1280×720
- Codec: per-frame JPEG over WebSocket binary frames
- Disconnect handling: 30s timeout, sidecar pauses login flow until
  reconnect

### TR-4: Screenshot Storage
- Per-attempt screenshots stored on sidecar volume during the attempt
- On `submitted` / `failed` / `rejected` finalization, uploaded to Joblign
  backend via `POST /api/jobs/{job_id}/auto-apply/{attempt_id}/artifacts`
- Backend stores in object storage (TODO: choose — S3-compatible or local
  filesystem; for v1 local filesystem at `/data/artifacts/{user_id}/{job_id}/{attempt_id}/`)
- Retention: 90 days, then expired by a nightly cron
- Max total per attempt: 50 MB (drop lower-priority screenshots if exceeded)

### TR-5: LLM Selection for Form Interpretation
- Same `MODEL_ENDPOINT` (Ollama Cloud) as existing Joblign agents
- Default model for form classification: `minimax-m3` (job parsing model —
  good at structured extraction)
- Fallback model: `qwen3.5` (used for cover letter generation; good at
  nuanced matching)
- Per-call timeout: 30s
- Per-form total LLM budget: $0.10 (tracked locally; halt if exceeded)

### TR-6: Joblign Backend Schema Changes
New tables:
- `user_profiles` (1:1 with users)
- `profile_education` (1:N)
- `profile_work_history` (1:N)
- `qa_entries` (1:N with users)
- `application_attempts` (1:N with jobs)
- `application_screenshots` (1:N with application_attempts, optional —
  could be JSON in attempts table for v1)

Migration strategy: add Alembic migrations under `backend/alembic/versions/`,
extend `init_db()` migration-on-startup logic. Existing tables unchanged.

### TR-7: Joblign Frontend Changes
- New "Profile" tab in settings: profile form + education/work history
  management
- New "Q&A Library" tab: Q&A bank CRUD with search
- New "Auto-Apply" panel on Job detail view: trigger button, status display,
  review screen (when staged), screenshots gallery, approve/reject/takeover
  buttons
- New "Manual Login" modal: viewport stream + credential input

### TR-8: Background Job Orchestration
- Auto-apply triggered via FastAPI `BackgroundTasks` (parity with cover
  letter generation)
- Progress polling endpoint: `GET /api/jobs/{job_id}/auto-apply/status`
- Status changes pushed to frontend via Server-Sent Events (SSE) OR polling
  (SSE preferred for live UX)

### TR-9: Sidecar Session Lifecycle
- Idle sessions auto-terminate after 10 minutes of no activity
- Maximum concurrent sessions per user: 1 (queue additional triggers)
- Maximum total concurrent sessions across all users: 4 (memory bound)
- Session state persisted to sidecar volume; survives sidecar restart

### TR-10: Security Boundaries
- No credentials ever written to logs, DB, or persistent storage (except
  during the live manual-login flow, which is in-memory only)
- Browser profiles (with stored cookies) live in the sidecar volume, NOT in
  the Joblign backend
- Joblign backend has no direct network access to job boards; all such
  traffic flows through the sidecar
- All Joblign ↔ sidecar traffic is internal Docker network only

### TR-11: Observability
- Sidecar logs every action with structured fields: `session_id`,
  `attempt_id`, `user_id`, `job_id`, `action`, `result`, `latency_ms`
- Backend logs attempt lifecycle events at INFO; LLM decisions at DEBUG
- Joblign frontend surfaces attempt progress + errors via existing toast
  notification system

### TR-12: Deployment Integration
- New `portainer/stacks/auto-apply.yml` in `my-stack`
- `deploy-patrick-mini.sh` extended to bring up `auto-apply` service
  (alongside existing 5 stacks: network → traefik → fetcher → vault → jobapp
  → auto-apply)
- New Vault secrets: `AUTO_APPLY_HMAC_TOKEN` (shared between Joblign and
  sidecar), `AUTO_APPLY_DATA_DIR` (path on host for persistent volume)
- Traefik labels: none (internal-only, same as fetcher)

---

## Objective Pass/Fail Test Criteria

Each requirement maps to one or more test cases. Tests are organized into
**unit**, **integration**, **end-to-end**, and **acceptance** tiers. A
requirement is **passing** when all its acceptance-tier tests pass.

### Test Tier Definitions
- **Unit:** isolated logic, no external dependencies
- **Integration:** backend ↔ DB ↔ sidecar, with mocked external services
- **End-to-end:** real Playwright against a local test form (HTML fixture)
- **Acceptance:** real Playwright against a real job board in a controlled
  test account

### UR-1: Assisted Application Submission
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR1-1 | Acceptance | Trigger auto-apply on a real LinkedIn Easy Apply job | Form filled, sidecar halted at submit, attempt state = `staged` |
| T-UR1-2 | Acceptance | Trigger auto-apply, then wait 5 minutes without approving | Attempt state remains `staged`; no submission occurs; session stays alive |

### UR-2: Pre-Fill Personal & Employment Data
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR2-1 | Unit | Profile CRUD endpoints validate and persist all FR-1 fields | All field types round-trip cleanly |
| T-UR2-2 | Integration | Sidecar reads profile from backend during fill | Every profile field used to fill matching form field |
| T-UR2-3 | E2E | Submit auto-apply with empty profile | Every form field surfaced as "Needs your input"; no half-fills |

### UR-3: Long-Tail Question Library
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR3-1 | Unit | Q&A CRUD endpoints | All operations round-trip |
| T-UR3-2 | Integration | Sidecar retrieves Q&A matches for a sample question | Top-3 results returned with similarity scores |
| T-UR3-3 | E2E | Form contains "Tell us about yourself" + matching Q&A exists | Sidecar uses the Q&A answer as the field value |

### UR-4: Pre-Submit Review
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR4-1 | Integration | Sidecar returns field report + per-field screenshots | All fields present; screenshots non-empty and within size budget |
| T-UR4-2 | E2E | Review screen renders field report | Every field visible with value, screenshot, and confidence |
| T-UR4-3 | E2E | Submit button disabled until review viewed | Initial state disabled; after viewing fields, enabled |
| T-UR4-4 | E2E | Low-confidence fields surface as "Needs your input" | Fields with conf < 0.7 not auto-filled; marked in UI |

### UR-5: One-Click Submit Approval
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR5-1 | Acceptance | Approve a staged attempt against real job board | Submission occurs; job stage = `Applied`; attempt state = `submitted` |
| T-UR5-2 | Integration | Submission failure (mocked) | Attempt state = `failed`; job stage unchanged; error report saved |

### UR-6: Resume + Cover Letter Auto-Upload
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR6-1 | E2E | Form has file upload labeled "Resume" | Sidecar uploads the generated resume DOCX for this job |
| T-UR6-2 | E2E | Form has file upload labeled "Cover Letter" | Sidecar uploads a PDF-rendered cover letter |
| T-UR6-3 | E2E | Form rejects DOCX, accepts PDF | Sidecar converts DOCX → PDF and re-uploads |

### UR-7: Manual Login Recovery
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR7-1 | E2E | Sidecar hits LinkedIn login wall | Viewport stream opens in Joblign; credential modal appears |
| T-UR7-2 | E2E | User enters credentials via modal | Sidecar types into actual page; post-login state detected; session resumes |
| T-UR7-3 | Unit | No credentials written to logs or DB after login | Grep test on logs and DB for known password patterns returns zero matches |

### UR-8: Smart Failure Recovery
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR8-1 | E2E | Click target has stale selector | First retry succeeds with new selector |
| T-UR8-2 | E2E | Click fails twice; LLM diagnosis proposes alternate strategy | Sidecar attempts LLM's strategy; if successful, continues |
| T-UR8-3 | E2E | All 3 attempts fail | Session halts; state = `failed`; "Manual Recovery Required" surfaced |
| T-UR8-4 | Unit | Total LLM budget capped at $0.10 per form | Halt triggered when budget exceeded |

### UR-9: Submission Audit Trail
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR9-1 | Integration | Complete attempt record after success | All audit fields (URL, timestamps, field report, screenshots, LLM log, confirmation) present |
| T-UR9-2 | E2E | Job detail view shows attempt history | Timeline + screenshots gallery render correctly |

### UR-10: Form Rejection & Manual Takeover
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-UR10-1 | E2E | Reject a staged attempt | Job stage = `draft`; session preserved; can be inspected |
| T-UR10-2 | E2E | Trigger manual takeover | Job stage = `saved`; sidecar viewport live-streamed to user |
| T-UR10-3 | E2E | Trigger new attempt on a job with prior attempts | New attempt created; previous attempts preserved |

### Cross-Cutting: TR-1 (Sidecar Architecture)
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-TR1-1 | Integration | Sidecar service reachable from Joblign via `proxy` network | Healthcheck returns 200; auth token validated |
| T-TR1-2 | Integration | Sidecar NOT reachable from public internet | External HTTP probe times out / connection refused |
| T-TR1-3 | Integration | Sidecar security posture verified | Container runs with read-only root, no-new-privileges, all-caps dropped |

### Cross-Cutting: TR-2 (Auth)
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-TR2-1 | Unit | Sidecar rejects requests without valid HMAC token | 401 returned |
| T-TR2-2 | Unit | Sidecar accepts requests with valid HMAC token | 200 returned |

### Cross-Cutting: TR-4 (Screenshot Storage)
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-TR4-1 | Integration | Screenshots uploaded to backend on attempt finalization | Files present in `/data/artifacts/{user_id}/{job_id}/{attempt_id}/` |
| T-TR4-2 | Integration | Screenshots >90 days old purged | Nightly cron removes them |
| T-TR4-3 | Integration | Attempt >50 MB triggers screenshot eviction | Lowest-priority screenshots removed first; attempt continues |

### Cross-Cutting: TR-9 (Session Lifecycle)
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-TR9-1 | Integration | Idle session auto-terminates after 10 min | Session closed; resources released |
| T-TR9-2 | Integration | 5 concurrent sessions requested by one user | 4th+ queued, not started |
| T-TR9-3 | Integration | 5 concurrent sessions system-wide | 5th+ rejected with 503 |

### Cross-Cutting: TR-10 (Security)
| ID | Type | Description | Pass Criterion |
|---|---|---|---|
| T-TR10-1 | Unit | No credential patterns in logs after a full apply cycle | Grep test passes |
| T-TR10-2 | Unit | No credential patterns in DB after a full apply cycle | SQL query test passes |
| T-TR10-3 | Integration | Joblign backend has no network route to job boards | DNS + connection test fails from Joblign container |

---

## Open Questions (Resolved)

| # | Question | Resolution |
|---|---|---|
| 1 | Submission autonomy level | Assisted only (user approves) |
| 2 | Board coverage | LLM-driven per-form (no per-board hardcoding) |
| 3 | Authentication to boards | Headless session + manual login streaming |
| 4 | Profile data scope | Comprehensive (full FR-1) |
| 5 | Review UI fidelity | Per-field screenshots + structured diff |
| 6 | Failure handling | Smart retry with LLM diagnosis (3 attempts max) |

---

## Out of Scope for v1

- Autonomous submission (no human approval before click)
- Multi-user / multi-tenant profile sharing
- Form templates or auto-fill suggestions across users
- Salary negotiation scripting
- Interview scheduling automation
- Application analytics / success-rate tracking beyond what Joblign already provides
- Multi-language form support (English-only for v1)
