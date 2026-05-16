# Implementation Tasks: Descope Auth Migration

## Overview

Migrate meeting-master from broken Google OAuth to Descope authentication.
- **Current Status**: ✅ **COMPLETED** — Descope auth deployed and verified
- **Target**: Descope sign-in (same as vivah/bio-bandish) + guest mode
- **Project**: `/root/ideas/meeting-master/` (source), `/root/docker/meeting-master/` (Docker)
- **Completed**: 2026-04-06

## Tasks

- [x] 1. **Backend: Create `auth.py` module**
  - Create `/root/ideas/meeting-master/backend/auth.py`
  - Import `LehanaAuthConfig`, `require_auth`, `require_tier`, `require_admin` from `lehana_auth`
  - Configure with `app_name="meeting-master"`, `auth_service_url` from config
  - Export `require_auth` decorator, `optional_auth` decorator, helper functions
  - Model on: `/root/ideas/bio-bandish/backend/auth.py`
  - _Requirements: R2_

- [x] 2. **Backend: Update `config.py`**
  - Add `AUTH_SERVICE_URL`, `DESCOPE_PROJECT_ID`, `APP_NAME_IN_AUTH` constants
  - Keep `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRE_HOURS` (for guest tokens)
  - Remove/deprecate `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
  - _Requirements: R2, R4_

- [x] 3. **Backend: Rewrite auth layer in `api.py`**
  - Remove imports: `from jose import JWTError, jwt`, `from google.oauth2 import id_token`, `from google.auth.transport import requests as google_requests`
  - Keep `jose` import for guest token endpoint only
  - Remove `get_current_user()` function (lines 104-156)
  - Remove `require_auth()` function (lines 160-164)
  - Import `require_auth`, `optional_auth` from new `auth.py` module
  - _Requirements: R2, R5_

- [x] 4. **Backend: Migrate all `Depends(require_auth)` endpoints**
  - Convert every `user: dict = Depends(require_auth)` to `@require_auth` decorator pattern
  - User info accessed via `request.state.user` instead of `user` parameter
  - Map field names: `request.state.user["id"]` instead of `user["user_id"]`
  - Affected endpoints: `/api/v1/auth/me`, `/api/v1/settings`, `/api/v1/team/*`, `/api/v1/meetings/*` (all CRUD), `/api/v1/meetings/upload`, `/api/v1/meetings/{id}/google-tools`
  - _Requirements: R2, R3, R5_

- [x] 5. **Backend: Migrate auth endpoints**
  - Remove `POST /api/v1/auth/google` endpoint (lines 609-695)
  - Modify `GET /api/v1/auth/config` to return Descope config instead of Google config
  - Keep `POST /api/v1/auth/guest` (still issues local JWT)
  - Add `POST /api/v1/auth/refresh` endpoint (proxy to auth-service)
  - Modify `GET /api/v1/auth/me` to use `request.state.user` instead of `Depends(require_auth)`
  - _Requirements: R3_

- [x] 6. **Checkpoint: Backend syntax + import validation**
  - Run `python -m py_compile backend/api.py` (inside container or with PYTHONPATH)
  - Verify all imports resolve
  - Check no circular imports between auth.py and config.py

- [x] 7. **Frontend: Replace Google SDK with Descope in `index.html`**
  - Remove: `<script src="https://accounts.google.com/gsi/client" async defer></script>`
  - Add: `<script src="https://unpkg.com/@descope/web-component@latest/dist/index.js"></script>`
  - Replace auth screen HTML: `<div id="google-signin-btn">` → `<div id="descopeWidget">`
  - Keep "Continue as Guest" button
  - _Requirements: R1_

- [x] 8. **Frontend: Rewrite auth flow in `app.js`**
  - Add Descope config constants: `DESCOPE_PROJECT_ID`, `DESCOPE_FLOW_ID`, token keys
  - Remove: `initGoogleAuth()` method (~lines 96-145), `handleGoogleSignIn()` method (~lines 195-220)
  - Add: `initDescopeAuth()` — create `<descope-wc>` element, attach success/error listeners
  - Add: `handleDescopeSuccess(detail)` — extract sessionJwt, refreshJwt, user info → store in localStorage
  - Modify: `init()` — call `initDescopeAuth()` instead of `initGoogleAuth()`
  - Modify: `authFetch()` — add 401 retry with token refresh
  - Modify: `logout()` — also clear refresh token + user info
  - Keep: `continueAsGuest()` — unchanged
  - _Requirements: R1, R5_

- [x] 9. **Docker: Update `docker-compose.yml`**
  - Add volume: `/root/repo/lehana-auth:/opt/lehana-auth:ro`
  - Add env: `PYTHONPATH=/opt/lehana-auth`
  - Add env: `AUTH_SERVICE_URL`, `DESCOPE_PROJECT_ID`, `APP_NAME_IN_AUTH`
  - Remove env: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
  - _Requirements: R4_

- [x] 10. **Docker: Update `requirements.txt`**
  - Remove: `google-auth==2.25.2`, `google-auth-oauthlib==1.2.0`, `google-auth-httplib2==0.2.0`
  - Keep: `python-jose[cryptography]==3.3.0` (for guest tokens), `httpx==0.26.0` (used by lehana_auth)
  - _Requirements: R4_

- [x] 11. **Docker: Rebuild and deploy**
  - `cd /root/docker/meeting-master && docker compose build --no-cache && docker compose up -d`
  - Verify: `docker logs meeting-master --tail 30` — no import errors
  - Verify: `curl -s https://meeting.aidhunik.com/health | jq` — healthy
  - _Requirements: R4_

- [x] 12. **Test: Auth config endpoint**
  - `curl -s https://meeting.aidhunik.com/api/v1/auth/config | jq` — returns Descope config
  - Verify: `descope_enabled: true`, `descope_project_id` present, `guest_mode_enabled: true`
  - _Requirements: R3_

- [x] 13. **Test: Guest mode**
  - `curl -s -X POST https://meeting.aidhunik.com/api/v1/auth/guest | jq` — returns JWT
  - Use guest token: `curl -s -H "Authorization: Bearer <token>" https://meeting.aidhunik.com/api/v1/auth/me | jq`
  - _Requirements: R5_

- [x] 14. **Test: Descope frontend widget**
  - Open `https://meeting.aidhunik.com/` in browser
  - Verify: Descope widget renders (not broken Google button)
  - Verify: "Continue as Guest" button still present
  - _Requirements: R1_

- [x] 15. **Git: Initialize repo and push**
  - `cd /root/ideas/meeting-master && git init`
  - Add `.gitignore` (Python, node_modules, __pycache__, .env, data/)
  - `git add -A && git commit -m "feat: migrate auth from Google OAuth to Descope"`
  - `git remote add origin git@gitlab.com:paras-lehana/meeting-master.git`
  - `git push -u origin main`
  - _Requirements: R4_
