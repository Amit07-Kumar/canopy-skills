# Design: Descope Auth Migration

## Overview

Replace meeting-master's broken Google OAuth + custom JWT authentication with the platform-standard Descope authentication pattern. The core change is:

- **Frontend**: Google Sign-In SDK → Descope `<descope-wc>` web component
- **Backend**: Custom JWT decode (python-jose) → `lehana_auth` library calling centralized `auth-service`
- **Docker**: Add `lehana-auth` volume mount + auth env vars

## Architecture

### Current Architecture (Broken)

```
Frontend (app.js)
  ├─ Google Sign-In SDK → POST /api/v1/auth/google → local JWT (HS256)
  ├─ Guest Mode → POST /api/v1/auth/guest → local JWT (HS256)
  └─ Token stored in localStorage['mm_token']

Backend (api.py)
  ├─ get_current_user(): jwt.decode(token, JWT_SECRET, HS256) → ES lookup
  ├─ require_auth(): Depends → returns user dict
  └─ Google OAuth: verify_oauth2_token → create user in ES → issue JWT
```

**Problem**: `GOOGLE_CLIENT_ID` is a placeholder → Google button shows "not configured" → only guest mode works.

### Target Architecture (Descope)

```
Frontend (app.js)
  ├─ Descope <descope-wc> widget → on success: stores sessionJwt in localStorage
  ├─ Guest Mode → POST /api/v1/auth/guest → local JWT (preserved)
  └─ Both tokens sent as: Authorization: Bearer <token>

Backend (api.py)
  ├─ auth.py imports lehana_auth → calls auth-service /v1/authorize
  ├─ require_auth decorator: validates Descope JWT via auth-service → sets request.state.user
  ├─ optional_auth decorator: tries Descope, falls back to guest JWT
  └─ Guest JWT: still decoded locally via python-jose (backward compat)

Docker
  ├─ Volume: /root/repo/lehana-auth → /opt/lehana-auth:ro
  ├─ PYTHONPATH=/opt/lehana-auth
  └─ AUTH_SERVICE_URL=https://auth.lehana.in
```

## Technology Stack

- **Auth SDK**: Descope web-component (`@descope/web-component@latest`) via CDN
- **Auth Backend**: `lehana_auth` library (FastAPI decorators, httpx to auth-service)
- **Auth Service**: Centralized at `auth.lehana.in` (Descope Python SDK, RSA JWT validation)
- **Auth Config**: Descope Project ID `P39NXXbIdxR73iGD6sJV3EUyPFYv`, Flow ID `sign-up-or-in-passwords-or-social`
- **App Name**: `meeting-master` (Descope custom attribute key: `apps.meeting-master.tier`)
- **Guest Tokens**: Local JWT via `python-jose` (HS256, 24h expiry)

## Components and Interfaces

### 1. Frontend Auth Flow (app.js)

**Responsibilities**:
- Render Descope widget on auth screen
- Handle successful auth → store tokens → load main app
- Attach token to API requests via `authFetch()`
- Handle 401 responses → attempt refresh → logout on failure
- Preserve guest mode

**Key Changes**:
```
REMOVE: initGoogleAuth(), handleGoogleSignIn()
REMOVE: Google Sign-In SDK script tag
ADD: initDescopeAuth() — creates <descope-wc> element
ADD: handleDescopeSuccess(e.detail) — stores sessionJwt, refreshJwt
ADD: refreshToken() — calls /api/v1/auth/refresh
MODIFY: authFetch() — add 401 retry with refresh
MODIFY: logout() — also clear refresh token
KEEP: continueAsGuest() — unchanged
KEEP: authFetch() Bearer token format — unchanged
```

**Descope Widget Config**:
```javascript
const DESCOPE_PROJECT_ID = 'P39NXXbIdxR73iGD6sJV3EUyPFYv';
const DESCOPE_FLOW_ID = 'sign-up-or-in-passwords-or-social';
const TOKEN_KEY = 'mm_token';           // Keep existing key for backward compat
const REFRESH_TOKEN_KEY = 'mm_refresh_token';
const USER_KEY = 'mm_user_info';
```

### 2. Backend Auth Module (auth.py — NEW)

**Responsibilities**:
- Configure `lehana_auth` with app name and auth-service URL
- Export configured decorators: `require_auth`, `optional_auth`, `require_tier`
- Provide helpers: `get_user_tier()`, `get_user_id()`

**Interface**:
```python
# auth.py — modeled on bio-bandish/backend/auth.py
from lehana_auth import LehanaAuthConfig, require_auth as la_require_auth
from lehana_auth import require_tier as la_require_tier, require_admin as la_require_admin

auth_config = LehanaAuthConfig(
    app_name="meeting-master",
    auth_service_url=AUTH_SERVICE_URL  # from config.py
)

# Configured decorators
require_auth = la_require_auth(auth_config)       # Validates via auth-service
optional_auth = ...                                 # Falls back to guest on failure

# Helpers 
def get_user_tier(request) -> str: ...
def get_user_id(request) -> str: ...
```

### 3. Backend API Changes (api.py)

**Key Migration Points**:

| Current Pattern | New Pattern |
|---|---|
| `user: dict = Depends(require_auth)` | `@require_auth` decorator, then `request.state.user` |
| `get_current_user(authorization)` | Removed — handled by `lehana_auth` |
| `POST /api/v1/auth/google` | Removed — Descope handles OAuth |
| `GET /api/v1/auth/config` | Returns Descope config instead of Google config |
| `POST /api/v1/auth/guest` | Preserved — still issues local JWT |

**Endpoint Signature Migration**: Every endpoint currently using `user: dict = Depends(require_auth)` changes to use the decorator pattern:

```python
# BEFORE:
@app.get("/api/v1/settings")
async def get_settings(user: dict = Depends(require_auth)):
    user_id = user["user_id"]
    ...

# AFTER:
@app.get("/api/v1/settings")
@require_auth
async def get_settings(request: Request):
    user_id = request.state.user["id"]  # Note: 'id' not 'user_id' in lehana_auth
    ...
```

### 4. Config Changes (config.py)

**Add**:
```python
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "https://auth.lehana.in")
DESCOPE_PROJECT_ID = os.getenv("DESCOPE_PROJECT_ID", "P39NXXbIdxR73iGD6sJV3EUyPFYv")
APP_NAME_IN_AUTH = os.getenv("APP_NAME_IN_AUTH", "meeting-master")
```

**Keep** (for guest token support):
```python
JWT_SECRET_KEY = ""   # Still used for guest tokens
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
```

**Remove/Deprecate**:
```python
GOOGLE_CLIENT_ID = ""      # No longer used
GOOGLE_CLIENT_SECRET = ""  # No longer used
GOOGLE_REDIRECT_URI = ...  # No longer used
```

### 5. Docker Changes (docker-compose.yml)

**Add volumes**:
```yaml
volumes:
  # ... existing mounts ...
  # lehana-auth shared auth package
  - /root/repo/lehana-auth:/opt/lehana-auth:ro
```

**Add environment**:
```yaml
environment:
  # ... existing vars ...
  - PYTHONPATH=/opt/lehana-auth
  - AUTH_SERVICE_URL=${AUTH_SERVICE_URL:-https://auth.lehana.in}
  - DESCOPE_PROJECT_ID=${DESCOPE_PROJECT_ID:-P39NXXbIdxR73iGD6sJV3EUyPFYv}
  - APP_NAME_IN_AUTH=${APP_NAME_IN_AUTH:-meeting-master}
```

**Remove env vars**:
```yaml
# Remove these — no longer needed
- GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
- GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
```

## User Data Model

**Before**: Users stored in the app persistence layer with `user_id`, `email`, `name`, `google_id`, etc.

**After**: Authenticated users managed by Descope. The `request.state.user` from `lehana_auth` provides:
```python
{
    "id": "U2xxxxxxxDescopeUserId",
    "email": "user@example.com",
    "name": "User Name",
    "tier": "FREE",  # or "PAID", "PREMIUM", "ADMIN"
    "raw": { ... }   # Full Descope user object
}
```

**Migration Notes**:
- Meetings are associated by `user_id` in ES. After migration, new meetings use Descope user ID.
- Existing guest meetings remain accessible via guest token (local JWT).
- No data migration needed — old and new user IDs coexist in meeting records.

## API Endpoints (Post-Migration)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api/v1/auth/config` | GET | None | Returns Descope config (project ID, flow ID, guest enabled) |
| `/api/v1/auth/guest` | POST | None | Issue local guest JWT |
| `/api/v1/auth/me` | GET | Descope JWT | Return user profile from request.state.user |
| `/api/v1/auth/refresh` | POST | None | Proxy refresh token to auth-service |
| `/api/v1/settings` | GET/PUT | Descope/Guest JWT | User settings |
| `/api/v1/meetings/*` | CRUD | Descope/Guest JWT | Meeting operations |
| `/health` | GET | None | Health check |

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| auth-service down → all auth fails | High | Guest mode still works (local JWT); auth-service has health monitoring |
| lehana_auth library breaking changes | Medium | Volume-mounted read-only; library is stable (v0.1.0) |
| Existing guest tokens invalidated | Low | Guest tokens use separate local JWT validation, unaffected by Descope migration |
| `request.state.user` field names differ from current `user` dict | Medium | Map field names in transition: `id` vs `user_id` |
