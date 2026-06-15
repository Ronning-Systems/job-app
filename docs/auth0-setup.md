# Auth0 Setup Guide for JobSync

This guide walks through configuring Auth0 as the identity provider for JobSync.

## 1. Create an Auth0 Account

1. Go to [auth0.com](https://auth0.com) and sign up for a free account.
2. Choose a tenant region closest to your users (e.g., US).
3. Note your tenant domain (e.g., `dev-abc123.us.auth0.com`) -- you will need this as `AUTH0_DOMAIN`.

## 2. Create a Single Page Application

1. In the Auth0 Dashboard, go to **Applications** > **Applications** and click **Create Application**.
2. Name it `JobSync` and select **Single Page Web Applications** as the application type.
3. In the **Settings** tab, configure:

   **Allowed Callback URLs:**
   ```
   http://localhost:8000,https://jobsync-XXXXX-uc.a.run.app
   ```

   **Allowed Logout URLs:**
   ```
   http://localhost:8000,https://jobsync-XXXXX-uc.a.run.app
   ```

   **Allowed Web Origins:**
   ```
   http://localhost:8000,https://jobsync-XXXXX-uc.a.run.app
   ```

4. Click **Save Changes**.
5. Note the **Client ID** -- this will be `AUTH0_CLIENT_ID` in the frontend configuration.

## 3. Create an API

1. Go to **Applications** > **APIs** and click **Create API**.
2. Name it `JobSync API`.
3. Set the **Identifier** to `https://jobsync/api` -- this is the `AUTH0_AUDIENCE` value.
4. Keep **RS256** as the signing algorithm.
5. Under **Settings**, enable **Allow Offline Access** (required for refresh tokens).
6. Click **Save**.

## 4. Configure Refresh Tokens

1. Go to **Applications** > **Applications** and open the JobSync SPA created in step 2.
2. Scroll to **Refresh Token** settings (or find them under **Applications** > **Advanced** depending on your Auth0 plan).
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
   - Use Auth0 dev keys for testing, or configure your own GitHub OAuth App credentials.
4. Click **Save**.

> **Note:** Auth0 dev keys work for development but you must provide your own credentials for production.

## 6. Update Configuration

### Frontend

Set these environment variables (or configure in the frontend auth module):

| Variable | Value |
|---|---|
| `AUTH0_DOMAIN` | Your tenant domain (e.g., `dev-abc123.us.auth0.com`) |
| `AUTH0_CLIENT_ID` | The Client ID from step 2 |

### Backend

Set these environment variables in `.env` (local) or Cloud Run (production):

| Variable | Value |
|---|---|
| `AUTH0_DOMAIN` | Your tenant domain (e.g., `dev-abc123.us.auth0.com`) |
| `AUTH0_AUDIENCE` | `https://jobsync/api` |
| `CORS_ORIGIN` | `http://localhost:8000` (local) or your Cloud Run URL (production) |

### Cloud Run

Update `cloudbuild.yaml` with your actual `AUTH0_DOMAIN` value, replacing `YOUR_AUTH0_DOMAIN`. Also update `CORS_ORIGIN` with your Cloud Run service URL, replacing the `XXXXX` placeholder.