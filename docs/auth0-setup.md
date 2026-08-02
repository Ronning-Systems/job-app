# Auth0 Setup Guide for Joblign

This guide walks through configuring Auth0 as the identity provider for Joblign.

> The legacy Auth0 API identifier `https://jobsync/api` is intentionally
> retained — it is an opaque identifier registered in the Auth0 dashboard,
> not a user-visible brand string. Renaming it requires reconfiguring the
> Auth0 dashboard API identifier and breaks all active sessions.

## 1. Create an Auth0 Account

1. Go to [auth0.com](https://auth0.com) and sign up for a free account.
2. Choose a tenant region closest to your users (e.g., US).
3. Note your tenant domain (e.g., `dev-abc123.us.auth0.com`) — you will need this as `AUTH0_DOMAIN`.

## 2. Create a Single Page Application

1. In the Auth0 Dashboard, go to **Applications** > **Applications** and click **Create Application**.
2. Name it `Joblign` and select **Single Page Web Applications** as the application type.
3. In the **Settings** tab, configure:

   **Application Login URI:** `https://joblign.ronning.systems`
   *(Where Auth0 should redirect users who hit the tenant URL directly. Point this at the SPA, not the Auth0 domain itself.)*

   **Allowed Callback URLs:**
   ```
   http://localhost:8765, https://joblign.ronning.systems
   ```

   **Allowed Logout URLs:**
   ```
   http://localhost:8765, https://joblign.ronning.systems
   ```

   **Allowed Web Origins:**
   ```
   http://localhost:8765, https://joblign.ronning.systems
   ```

   > **Safari + custom domain gotcha:** all three of the lists above MUST include
   > the SPA's exact origin (e.g. `https://joblign.ronning.systems`). Safari's
   > Intelligent Tracking Prevention blocks cross-origin POSTs to the token
   > endpoint if the SPA origin isn't in **Web Origins**. Missing entries here
   > cause silent refresh failures and (with the old `logout()`-on-error flow)
   > redirect cycles. The current production settings already include the right
   > entries — keep them when re-creating the SPA in a new tenant.

4. Under **Advanced Settings** > **Grant Types**, ensure **Authorization Code** and **Refresh Token** are enabled.
5. Set **Token Endpoint Authentication** to **None** (this is a SPA — it uses PKCE, not a client secret).
6. Click **Save Changes**.
7. Note the **Client ID** — this is `AUTH0_CLIENT_ID` in the frontend configuration.

## 3. Create an API

1. Go to **Applications** > **APIs** and click **Create API**.
2. Name it `Joblign API`.
3. Set the **Identifier** to `https://jobsync/api` — this is the `AUTH0_AUDIENCE` value used by both frontend and backend. (This opaque identifier is left as-is for backwards compatibility; do not rename it without rotating all sessions.)
4. Keep **RS256** as the signing algorithm.
5. Click **Save**.

## 4. Configure Refresh Tokens

1. Go to **Applications** > **Applications** and open the Joblign SPA created in step 2.
2. Scroll to **Refresh Token** settings.
3. Configure:
   - **Rotation Type:** Rotating
   - **Expiration Type:** Expiring
   - **Absolute Lifetime:** 30 days (2592000 seconds)
   - **Idle Lifetime:** 15 days (1296000 seconds)
4. Click **Save Changes**.

> **Note:** Rotating refresh tokens issue a new token on each use and revoke the old one, improving security.

## 5. Enable Social Connections

1. Go to **Authentication** > **Social**.
2. Enable **Google**:
   - Click **Google** and toggle it on.
   - Use Auth0 dev keys for testing, or configure your own Google OAuth credentials.
3. Enable **GitHub**:
   - Click **GitHub** and toggle it on.
   - Use Auth0 dev keys for testing, or configure your own GitHub GitHub App credentials.
4. Click **Save**.

> **Note:** Auth0 dev keys work for development but you must provide your own credentials for production.

## 6. Current Configuration

The following values are envsubst'd into `static/index.html` at deploy
time by `my-stack/deploy-patrick-mini.sh`. The values shown below are
the **source-tree defaults** (used as local-dev fallbacks when the api
is run without the envsubst pass, e.g. `run_local_docker.sh` without
the matching env vars set). The deployed prod and test envs read their
own per-env values from their respective `.env.patrick-mini[.test]`
files; see `my-stack/docs/auth0-setup.md` §6 for the per-env table.

| Variable | Source-tree default (local-dev fallback) |
|---|---|
| `AUTH0_DOMAIN` | `dev-saxftot48835pavp.us.auth0.com` (the test tenant; also the underlying tenant of the prod custom domain `auth.ronning.systems`) |
| `AUTH0_CLIENT_ID` | `sxWuSb9zcYbCv2Rwp1hEFbUNjgCyiUx8` (prod SPA Application) |
| `AUTH0_AUDIENCE` | `https://jobsync/api` (opaque, do not rename) |

The `static/index.html` source contains literal `${AUTH0_*}` placeholders.
To change the Auth0 wiring in any deployed env, edit the matching
`AUTH0_*` field in the env's `.env.patrick-mini[.test]` and re-run
the deploy. Do NOT edit `static/index.html` directly to set a real
client ID — the envsubst pass will overwrite it on the next build.

In production these values are also materialized from Vault by the
`jobapp-secrets-fetcher` sidecar (see `my-stack/portainer/stacks/jobapp.yml`);
the deploy orchestrator is `my-stack/deploy-patrick-mini.sh`.