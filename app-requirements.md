# Joblign — Get aligned for success (Functional Requirements / Actual Implementation)

## Overview
Joblign is an AI-powered job application tracking system: track applications
through a pipeline, parse job postings from text or URL, generate tailored
resumes and cover letters, and score them with ATS + industry-panel agents.
Tagline: "Get aligned for success".

## User Authentication ✅ Implemented
- **Auth0** identity provider with Google and GitHub social login
- JWT validation (PyJWT against Auth0 JWKS) on all `/api/*` endpoints
- Per-user data isolation — every table carries `user_id`; users see only
  their own jobs, resumes, and generated content
- Auto-provisioning on first login
- **Local-dev bypass:** `AUTH_DISABLED=true` returns a single shared dev
  user with no token check (production must never set this)
- Auth0 API identifier `https://jobsync/api` is an opaque identifier kept
  intentionally — renaming it requires reconfiguring the Auth0 dashboard
  and breaks active sessions

## Job Management

### Job Description Processing
- Paste plain text job descriptions — AI auto-parses company, position,
  location, salary, remote type
- **URL-only entry:** `POST /api/jobs/from-url` fetches, parses, and creates
  the job in one call. Tries direct httpx first; on 403/blocked/empty falls
  back to a headless-browser fetcher sidecar (`FETCHER_URL` env var, default
  `http://fetcher:8080`, Playwright+chromium). The frontend add-job modal
  is two-tab (From URL / Paste text)
- Extracts requirements (must-have / nice-to-have), responsibilities,
  keywords, and credentials
- Extracts structured pay range and application deadline where present

### Job Tracker Fields
- Company name
- Position / Job title
- Status / Stage (dropdown with 9 options)
- Job URL
- Location
- Remote capability (Remote / Hybrid / On-site)
- Salary information (free text, kept alongside structured pay)
- Structured pay range (`pay_range_min`/`pay_range_max`, `pay_currency`,
  `pay_period` — parsed from the posting; powers sort-by-pay)
- Application deadline (parsed from the posting; stored + sortable, no
  reminders/badges in v1)
- Applied date
- Notes / Comments
- Response received (checkbox)
- Application history timeline
- Required credentials (structured list)
- Globally unique `public_job_id` (short alphanumeric code, e.g.
  `JOB-A7K2M9P3`) shown on home screen and detail modal

### Job Stages (Implemented)
1. Saved
2. Applied
3. Phone Screen
4. Interview
5. Executive Call
6. Offered
7. Rejected
8. Withdrawn
9. Closed

## Resume Management

### Base Resumes
- Upload example resumes (PDF, DOCX, TXT) — used for AI voice/tone reference
- Upload resume templates (DOCX only) — the sole formatting source for
  generated resumes; one template per user enforced atomically
- View and delete uploaded base resumes

### Generated Resumes
- AI generates a tailored resume for a specific job
- Uses example resumes for content reference and the template for formatting
- Structured per-atom editor (cards derived from the template's captured
  style atoms); empty structured tab means the resume predates template
  atoms — regenerate once to populate both tabs
- Edit generated resume text; export to DOCX
- Regenerate resume for the same job
- Versioned revision history with text-based feedback

## Cover Letter Management

### Base Cover Letters
- Upload example cover letters (PDF, DOCX, TXT) — used as voice/tone
  reference for the generator (no template/DOCX variant in v1, only
  examples)
- View and delete uploaded base cover letters
- CRUD: `POST /api/cover-letters/base`, `GET /api/cover-letters/base`,
  `DELETE /api/cover-letters/base/{id}`

### Generated Cover Letters
- AI generates a tailored cover letter for a specific job, grounded in the
  candidate's resume and the job description; references example cover
  letters for tone
- Generation runs in the background (status poll route); latest generated
  resume is pulled automatically as the content reference
- Revision via text feedback — appends a versioned revision and updates
  `current_content`
- Regenerate / delete per job
- Routes: `POST /api/jobs/{job_id}/generate-cover-letter` (background +
  progress poll), `POST /api/jobs/{job_id}/revise-cover-letter`,
  `GET /api/jobs/{job_id}/generate-cover-letter/status`,
  `DELETE /api/jobs/{job_id}/cover-letter`

## AI Agent Capabilities

Models via Ollama Cloud (job parsing: minimax-m3, analysis: glm-5,
generation: qwen3.5 with gemma3:12b fallback).

### Job Parser Agent
- Parses pasted text or fetched URL job descriptions
- Extracts structured data: company, position, location, salary, remote type
- Identifies requirements (must-have / nice-to-have)
- Extracts responsibilities and keywords

### Resume Generator Agent
- Generates a customized resume for a specific job
- Matches content from example resumes to job requirements
- Applies template formatting
- Returns plain text resume content

### Cover Letter Generator Agent
- Generates a tailored cover letter for a specific job, grounded in the
  resume and job description
- Uses example cover letters for voice/tone reference only
- Plain text output (standard business letter format)
- Revision mode applies user feedback to the current letter

### ATS Analysis Agent
- Analyzes resume OR cover letter against job description
- Parseability, keyword match, search relevance, overall score (0-10)
- Critical issues, recommendations, keywords found and missing
- Returns structured JSON now persisted in `ArtifactScore`

### Technical Fit Analysis Agent
- Evaluates technical fit of resume for job
- Skill match, experience relevance, leadership fit scores
- Strengths, gaps, and recommendations

## Scoring Agents

Scores persist in the `ArtifactScore` table (one row per artifact +
score type; soft-FK to resume or cover letter, no orphan-blocking FK
constraint). Both resumes and cover letters can be scored.

### ATS Scoring (`ats-expert.md` prompt, extended)
- Returns structured scores: overall, parseability, keyword_match,
  search_relevance (0-10)
- Issues + recommendations lists, keywords found/missing
- Routes: `POST /api/jobs/{job_id}/resumes/{resume_id}/score-ats`,
  `POST /api/jobs/{job_id}/cover-letters/{cl_id}/score-ats`

### Industry Panel Scoring (`industry-panel.md` prompt)
- Single LLM call simulates 4 personas: engineering/technical leader,
  product leader, domain expert, recruiter — each scores 0-100 with a
  rationale, then a composite + per-persona summary
- Returns composite score, per-persona scores, strengths, gaps, and a
  recommendation ∈ {strong yes, yes, maybe, no, strong no}
- Routes: `POST /api/jobs/{job_id}/resumes/{resume_id}/score-industry-panel`,
  `POST /api/jobs/{job_id}/cover-letters/{cl_id}/score-industry-panel`
- Read back latest scores per job:
  `GET /api/jobs/{job_id}/scores` (latest per artifact_type +
  artifact_id + score_type; optional `?artifact_type=resume|cover_letter`)

## Dashboard & Statistics
- Live statistics: Total, Active, Interviews, Offers, Archived
- Clickable stat boxes act as filter tabs (All, Active, Interviewing, Offers,
  Archived)
- Two-column layout: Active and Archived applications
- Quick action buttons on job cards
- Sort-by-attribute on the jobs list: `GET /api/jobs?sort=company|position|
  location|stage|applied_date|deadline|pay|created&order=asc|desc`
- Non-blocking generation progress with notifications (persisted in
  localStorage under `joblignNotifications`)

## Technical Architecture
- **Backend:** FastAPI (Python 3.11) with SQLAlchemy ORM
- **Database:** PostgreSQL 16 in production, SQLite for local dev
- **Tables:** users, jobs, job_applications, base_resumes,
  generated_resumes, base_cover_letters, generated_cover_letters,
  artifact_scores
- **Frontend:** Single-page HTML/CSS/JavaScript (no build step); Joblign
  logo + favicon served at root
- **AI:** Ollama Cloud API
- **File Storage:** Base64 encoded in database
- **Auth:** Auth0 (Google + GitHub), JWT validation via PyJWT
- **Fetcher sidecar:** internal-only Playwright+chromium service (defined
  in `my-stack`, not this repo) for blocked job boards (LinkedIn, Indeed);
  reached via `FETCHER_URL` (default `http://fetcher:8080`); not exposed by
  Traefik
- **Deploy:** Docker image built on patrick-mini via
  `my-stack/deploy-patrick-mini.sh`; Traefik v3 reverse proxy with Let's
  Encrypt TLS; HashiCorp Vault for secrets. Public at
  `joblign.ronning.systems`. Cloud Run / GCP retired. The deploy brings up
  5 stacks (network → traefik → fetcher → vault → jobapp).

## Not Implemented (Future Features)
- Personal instructions for resume/cover-letter generation
- Deadline reminders / badges for upcoming application deadlines
- Multi-user organizational features