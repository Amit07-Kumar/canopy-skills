# Requirements: Descope Auth Migration

## Introduction

Meeting Master currently uses Google OAuth for authentication, but the Google Client ID was never configured (placeholder value `YOUR_GOOGLE_CLIENT_ID`). Every user sees "Google Sign-In not configured" and is forced to use Guest Mode. The Lehana.in platform has a working centralized auth system using Descope (same as vivah/bio-bandish) — this migration replaces the broken Google OAuth with the platform-standard Descope authentication.

## Project Context

- **Repository**: `/root/ideas/meeting-master/` (source), `/root/docker/meeting-master/` (deployment)
- **Tech Stack**: FastAPI (Python 3.11), Vanilla JS frontend, local JSON storage, Docker
- **Auth Provider (Target)**: Descope via `auth-service` at `auth.lehana.in`
- **Auth Library**: `lehana_auth` at `/root/repo/lehana-auth/`
- **Reference Implementation**: `/root/ideas/bio-bandish/` (vivah)
- **Target Users**: Meeting organizers using `meeting.aidhunik.com` / `meeting.lehana.in`

## Glossary

- **Descope**: Third-party identity-as-a-service provider used across Lehana.in platform
- **auth-service**: Centralized FastAPI service at `auth.lehana.in` that validates Descope JWTs
- **lehana_auth**: Shared Python library providing `require_auth`, `require_tier` decorators
- **SMK endpoint**: Shared Model Key — named AI endpoint on `llm.lehana.in` (not relevant here)
- **Guest Mode**: Unauthenticated fallback that issues a local JWT for temporary access

## Requirements

### R1: Descope Frontend Authentication

**User Story**: As a meeting organizer, I want to sign in with Google/email/social via Descope so I can have a persistent authenticated account.

#### Acceptance Criteria

1. WHEN the user opens `meeting.aidhunik.com`, THE app SHALL display a Descope sign-in widget (not a broken Google button)
2. WHEN the user completes Descope authentication, THE app SHALL store the session JWT and redirect to the main app screen
3. WHEN the user is already authenticated (JWT in localStorage), THE app SHALL skip the auth screen and load the main app
4. WHEN the Descope session JWT expires, THE app SHALL attempt a token refresh before logging out
5. THE auth screen SHALL still show a "Continue as Guest" button for unauthenticated access

### R2: Backend Descope Token Validation

**User Story**: As an API consumer, I want my Descope JWT to be validated by the centralized auth-service so that authentication is consistent across all Lehana.in services.

#### Acceptance Criteria

1. WHEN a request includes `Authorization: Bearer <descope_jwt>`, THE backend SHALL validate it via `lehana_auth` library calling `auth.lehana.in/v1/authorize`
2. WHEN validation succeeds, THE backend SHALL set `request.state.user` with user info (id, email, name, tier)
3. WHEN validation fails (expired/invalid token), THE backend SHALL return HTTP 401
4. THE guest auth endpoint (`POST /api/v1/auth/guest`) SHALL continue to work, issuing a local JWT
5. THE `AUTH_DISABLED` flag SHALL continue to bypass auth when set to `true`

### R3: Auth Endpoints Migration

**User Story**: As a frontend developer, I want clean auth endpoints that work with the Descope flow.

#### Acceptance Criteria

1. THE backend SHALL expose `GET /api/v1/auth/config` returning `{"descope_enabled": true, "descope_project_id": "...", "guest_mode_enabled": true}`
2. THE backend SHALL expose `GET /api/v1/auth/me` returning user profile from `request.state.user`
3. THE backend SHALL expose `POST /api/v1/auth/refresh` proxying refresh token to auth-service
4. THE backend SHALL remove the `POST /api/v1/auth/google` endpoint (no longer needed)
5. THE backend SHALL preserve `POST /api/v1/auth/guest` for guest access

### R4: Docker & Deployment

**User Story**: As a deployer, I want the container to have proper auth configuration without manual setup.

#### Acceptance Criteria

1. THE docker-compose SHALL mount `lehana-auth` library at `/opt/lehana-auth` (read-only)
2. THE docker-compose SHALL set `PYTHONPATH=/opt/lehana-auth` for the library to be importable
3. THE docker-compose SHALL include `AUTH_SERVICE_URL`, `DESCOPE_PROJECT_ID`, `APP_NAME_IN_AUTH` env vars
4. THE requirements.txt SHALL not include Google OAuth packages (`google-auth`, `google-auth-oauthlib`, `google-auth-httplib2`)
5. THE container SHALL pass health checks after rebuild

### R5: Backward Compatibility

**User Story**: As an existing guest user, I want my current guest sessions to still work.

#### Acceptance Criteria

1. WHEN a user has an existing guest JWT (`mm_token`), THE app SHALL accept it until expiry
2. WHEN guest mode is activated, THE backend SHALL still issue local JWTs (not Descope tokens)
3. ALL existing API endpoints using `Depends(require_auth)` SHALL work with both Descope and guest JWTs
