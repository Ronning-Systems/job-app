# Authentication & Data Privacy Design

**Date:** 2026-06-14
**Status:** Approved (post-security-review)
**Scope:** Add Auth0 authentication with per-user data isolation to JobSync

## Overview

JobSync currently has no authentication — all API endpoints are publicly accessible and all data is in a single shared pool. This spec adds:

1. **Auth0 authentication** with Google and GitHub social providers
2. **Per-user data isolation** — each user sees only their own jobs, resumes, and generated content
3. **JWT-based API protection** — all `/api/*` endpoints require a valid Auth0 access token

## Authentication Architecture

### Auth0 Configuration

- Create an Auth0 tenant (free tier — 25k MAU)
- Create a **Single Page Application** client for the frontend
- Create an **API** resource in Auth0 with identifier `https://jobsync/api`
- Enable social connections: Google, GitHub (Microsoft available on paid tier)
- Configure callback URLs: `https://<cloud-run-domain>`, `http://localhost:8000`
- Configure logout URLs: same as callback URLs
- Configure allowed origins: same domains
- **Enable refresh token rotation**: Set `rotation_type: "rotating"` and `expiration_type: "expiring"` on the Auth0 API. This is required for reliable session management in modern browsers (Safari ITP, Firefox ETP block third-party cookies, breaking silent auth iframe approaches)

### Authentication Flow

```
1. User visits app → SPA loads → no token detected → redirect to Auth0 login
2. User authenticates via Google/GitHub → Auth0 redirects back with auth code
3. SPA exchanges code for access token + refresh token (Auth0 SDK handles this)
4. Every API call includes: Authorization: Bearer <access_token>
5. Backend auth middleware validates JWT via Auth0 JWKS endpoint
6. If auth0_id not in users table → auto-provision user from ID token claims
   (with IntegrityError handling for concurrent request race condition)
7. All data queries filtered by user_id → user sees only their own data
```

### Key Design Decisions

- **Auth0 hosted login page** — no custom login UI to maintain
- **JWT validation on backend** — stateless, no session storage needed
- **Auto-provisioning with race condition safety** — first login creates user record; `UNIQUE` constraint on `auth0_id` plus `IntegrityError` catch prevents duplicates from concurrent requests
- **Cloud Run stays `--allow-unauthenticated`** — the app validates tokens internally; this lets the SPA load without IAM interference
- **Auth0 domain/audience are public config** — security comes from JWT signing keys, not secret config values
- **Default-auth middleware pattern** — all `/api/*` endpoints require auth by default, with explicit opt-out only for `GET /api/health`

## Database Changes

### New `users` Table

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER | Primary key, auto-increment |
| auth0_id | VARCHAR(255) | **UNIQUE constraint**, indexed. E.g., `google\|12345678` |
| email | VARCHAR(255) | From Auth0 ID token |
| name | VARCHAR(255) | Display name from provider |
| avatar_url | VARCHAR(512) | Profile picture URL |
| created_at | TIMESTAMP | Auto-set on creation |
| last_login | TIMESTAMP | Updated on each login |

### Modified Tables

All data tables gain a `user_id` column with foreign key to `users.id`:

- `jobs` → + `user_id INTEGER FK → users.id`
- `job_applications` → + `user_id INTEGER FK → users.id`
- `base_resumes` → + `user_id INTEGER FK → users.id`
- `generated_resumes` → + `user_id INTEGER FK → users.id`

### Migration Strategy

Existing data will be wiped. Since there is no production data to preserve, SQLAlchemy's `create_all` will create all tables fresh with the new schema. The `init_db()` startup function handles this automatically.

## Backend Changes

### New File: `backend/auth.py`

Responsible for JWT validation and user provisioning:

- **`verify_jwt(token, auth0_domain, audience)`** — validates token signature against Auth0 JWKS, checks issuer, audience, and expiry. **Hardcodes `algorithms=["RS256"]`** — never accepts algorithm as a parameter.
- **`get_current_user(token, db)`** — FastAPI dependency that extracts Bearer token, validates JWT, looks up or creates user in `users` table, returns `User` object. Handles `IntegrityError` from concurrent provisioning by catching the duplicate key error and re-querying.
- **`GET /api/auth/me`** — returns current user profile (id, email, name, avatar_url)

Uses **PyJWT** (not python-jose) for JWT decoding and `httpx` to fetch JWKS from Auth0. PyJWT enforces algorithm specification and is actively maintained — python-jose has unfixed algorithm confusion CVEs (CVE-2024-33663, CVE-2024-33664).

### Auth Middleware Pattern

Instead of adding `Depends(get_current_user)` endpoint by endpoint, use a **default-auth router pattern**:

- Create all `/api/*` routes on a router that requires `get_current_user` by default
- Health check (`GET /api/health`) is excluded or on a separate unauthenticated router
- This prevents accidentally adding unauthenticated endpoints

### Modified: `backend/models.py`

- Add `User` model with columns defined above
- Add `user_id = Column(Integer, ForeignKey("users.id"))` to `Job`, `JobApplication`, `BaseResume`, `GeneratedResume`
- Add `user = relationship("User")` to each model
- Keep existing columns and relationships intact

### Modified: `backend/main.py`

- Import `get_current_user` from `auth.py`
- Add `current_user: User = Depends(get_current_user)` to all API endpoints (except health check)
- Filter all read queries by `current_user.id`
- Set `user_id=current_user.id` on all create operations
- Add `/api/auth/me` endpoint
- **Fix CORS**: Set `allow_credentials=False` (Bearer tokens don't need it), restrict `allow_origins` to specific domains
- **Fix `/api/fetch-job` SSRF**: Add URL validation to block private IP ranges (RFC 1918), link-local addresses, loopback, and cloud metadata endpoint `169.254.169.254`

Endpoint-by-endpoint changes:

| Endpoint | Change |
|----------|--------|
| `POST /api/jobs` | Set `user_id=current_user.id` on new Job and JobApplication |
| `GET /api/jobs` | Filter by `current_user.id` |
| `GET /api/jobs/{id}` | Filter by `current_user.id`, return 404 if not owner |
| `PUT /api/jobs/{id}` | Verify ownership, then update |
| `DELETE /api/jobs/{id}` | Verify ownership, then delete |
| `PATCH /api/jobs/{id}/stage` | Verify ownership, then update |
| `POST /api/resumes/base` | Set `user_id=current_user.id` |
| `GET /api/resumes/base` | Filter by `current_user.id` |
| `DELETE /api/resumes/base/{id}` | Verify ownership, then delete |
| `POST /api/agents/ats-analysis` | Verify job ownership |
| `POST /api/agents/technical-fit` | Verify job ownership |
| `POST /api/jobs/{id}/generate-resume` | Verify job ownership |
| `POST /api/fetch-job` | Requires auth (prevent abuse as open proxy), SSRF protections applied |
| `GET /api/health` | No auth required (health check) |
| `GET /api/stats` | Filter by `current_user.id` |
| `GET /api/auth/me` | **New** — returns current user profile |

### Static File Serving

The SPA catch-all routes (`/`, `/{path}`) remain **unauthenticated** so the frontend can load and handle login redirects. Only `/api/*` endpoints require authentication.

### SSRF Protection for `/api/fetch-job`

The fetch-job endpoint accepts arbitrary URLs and fetches them server-side. To prevent abuse:

- Block requests to private/internal IP ranges: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16`
- Block requests to `169.254.169.254` specifically (GCP/AWS/Azure metadata endpoint)
- Restrict to HTTPS-only URLs
- Keep the existing 30-second timeout

## Frontend Changes

### Auth0 SPA SDK Integration

Add Auth0 SDK via CDN to `index.html`:

```html
<script src="https://cdn.auth0.com/js/auth0-spa-js/2.1/auth0-spa-js.production.js"></script>
```

### New Frontend Behavior

1. **On page load:** Check for authenticated session
   - If authenticated → show main app
   - If not → show login button / auto-redirect to Auth0

2. **Login button:** Calls `auth0Client.loginWithRedirect()`

3. **After Auth0 callback:** `auth0Client.handleRedirectCallback()` exchanges code for tokens

4. **Token management:** Store access token in memory (not localStorage — XSS risk)
   - On each API call, get token via `auth0Client.getTokenSilently()`
   - Attach as `Authorization: Bearer <token>` header
   - **Enable refresh tokens:** Configure `useRefreshTokens: true` in Auth0 SDK setup, with `cacheLocation: 'memory'`. This ensures sessions survive page refreshes and work in browsers with ITP/ETP.

5. **Logout button:** Calls `auth0Client.logout()`, clears local state

6. **User display:** Show user name and avatar in header

### Modified API Calls

All `fetch('/api/...')` calls wrapped with auth header injection:

```javascript
async function apiFetch(url, options = {}) {
  const token = await auth0Client.getTokenSilently();
  options.headers = {
    ...options.headers,
    'Authorization': `Bearer ${token}`,
  };
  return fetch(url, options);
}
```

### Error Handling

- **401 response** → Token expired or invalid → attempt silent token refresh → if still fails, redirect to login
- **403 response** → User trying to access another user's data → show error message

## Deployment Changes

### New Environment Variables

| Variable | Purpose | Example | Secret? |
|----------|---------|---------|---------|
| `AUTH0_DOMAIN` | Auth0 tenant domain | `dev-xxxxx.us.auth0.com` | No |
| `AUTH0_AUDIENCE` | API identifier | `https://jobsync/api` | No |

These are public configuration values — Auth0 security comes from JWT signing keys, not from hiding these values. They should be added to `cloudbuild.yaml` under `--set-env-vars`.

### Cloud Run Configuration

Cloud Run remains `--allow-unauthenticated` so the SPA can load without IAM interference. Authentication is handled at the application layer via JWT validation.

### CORS Configuration

Update CORS middleware:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:8000")],
    allow_credentials=False,  # Bearer tokens don't need credentials
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)
```

- Production: set `CORS_ORIGIN` to the Cloud Run domain
- Development: defaults to `http://localhost:8000`

### Auth0 Dashboard Setup

1. Create Auth0 account at auth0.com
2. Create a new tenant
3. Create a **Single Page Application**:
   - Allowed Callback URLs: `https://<cloud-run-domain>`, `http://localhost:8000`
   - Allowed Logout URLs: same
   - Allowed Web Origins: same
4. Create an **API**:
   - Identifier: `https://jobsync/api`
   - Signing algorithm: RS256
   - **Enable "Allow Offline Access"** for refresh token support
   - Set **Rotation Type: Rotating** and **Expiration Type: Expiring** for refresh tokens
5. Enable social connections:
   - Google (requires Google Cloud OAuth client ID/secret)
   - GitHub (requires GitHub OAuth app)

## New Dependencies

Add to `backend/requirements.txt`:

```
PyJWT[cryptography]>=2.8.0
```

Uses PyJWT (not python-jose) for JWT decoding and RSA signature verification. `httpx` (already a dependency) handles JWKS fetching.

### Dependency Upgrades (security fixes)

These existing dependencies have known CVEs and must be upgraded:

| Package | Current | Upgrade To | Reason |
|---------|---------|-----------|--------|
| fastapi | 0.109.0 | >=0.109.1 | CVE-2024-24762 (ReDoS via python-multipart) |
| python-multipart | 0.0.6 | >=0.0.18 | CVE-2024-24762 + CVE-2024-53981 (ReDoS) |
| httpx | 0.26.0 | >=0.27.0 | CVE-2023-47641 (HTTPS→HTTP redirect downgrade) |
| pypdf2 | 3.0.1 | **Remove, replace with pypdf>=3.17.0** | CVE-2023-36464 (DoS via crafted PDF), project deprecated |

For the PyPDF2 → pypdf migration: the import path changes from `PyPDF2` to `pypdf`, but the API is largely compatible.

## Security Considerations

1. **JWT validation is strict** — PyJWT with hardcoded `algorithms=["RS256"]`, never accepts algorithm as a parameter. Prevents algorithm confusion attacks.
2. **No token storage in localStorage** — tokens held in memory only, reducing XSS attack surface. Refresh tokens managed by Auth0 SDK in a web worker.
3. **CORS restricted** — specific origins only, `allow_credentials=False`
4. **Data isolation enforced at query level** — every query filters by `user_id`, no reliance on client-side filtering
5. **fetch-job requires authentication with SSRF protections** — blocks private IPs, metadata endpoints, and HTTP schemes
6. **Health endpoint remains open** — no auth required for health checks
7. **Auth0 handles all password security** — no passwords stored in the application database
8. **Default-auth middleware pattern** — all `/api/*` endpoints require auth by default, explicit opt-out only for health checks
9. **Race condition safety** — user auto-provisioning handles `IntegrityError` on duplicate `auth0_id`
10. **Refresh token rotation** — Auth0 configured with rotating refresh tokens to prevent token replay