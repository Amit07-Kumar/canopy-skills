---
name: auth-and-storage
description: Authentication modes (Descope production, guest-mode JWT, AUTH_DISABLED bypass for local dev) and the JSON-file persistence layer that backs meetings, users, and BRDs with RLock-protected atomic writes.
---

# Auth & Storage

## When to use this skill

- A user can't sign in / the UI shows "Auth Disabled" as their name.
- You're adding a new authenticated endpoint and need to choose between
  `require_auth` and `get_current_user`.
- A meeting record vanished / was corrupted — diagnose the storage layer.
- You need to migrate from JSON-file storage to a database without
  breaking the contract.

## Auth modes

### 1. Descope (production)

`meeting-master/backend/auth.py:require_auth`:

- Validates `Authorization: Bearer <jwt>` against the Descope project
  (`P39NXXbIdxR73iGD6sJV3EUyPFYv` by default).
- Returns user dict with `id`, `user_id`, `email`, `name`, `tier`, `is_guest`, `raw`.
- Tier comes from Descope custom claims.

Frontend integrates via `@descope/web-component` (loaded from CDN).
On successful sign-in, the SDK posts a session JWT to `POST
/api/v1/auth/descope-login` which exchanges it for the meeting-master
session token persisted in `localStorage.mm_token`.

### 2. Guest mode

`POST /api/v1/auth/guest`:

- Body: `{device_id, device_name}`.
- Returns `{access_token, refresh_token, user: {id, email: "", name: "Guest", is_guest: true}}`.
- The `access_token` is a meeting-master-issued JWT (HS256, 24h expiry).
- Frontend stores under `localStorage.mm_token` — same key as Descope.

The token field is **`access_token`** (NOT `token`). Early test scripts
that read `.token` were silently broken.

### 3. AUTH_DISABLED bypass

When `AUTH_DISABLED=true` in `.env` (used by `start-demo.ps1` for local
dev), `require_auth` returns a synthetic user:

```python
{
    "id":       "auth_disabled",
    "user_id":  "auth_disabled",
    "email":    "",
    "name":     "Auth Disabled",
    "tier":     "ADMIN",
    "is_guest": False,
    "raw":      {}
}
```

Frontend explicitly **suppresses the synthetic name** from the Name input
so the placeholder shows — see [[11-frontend-ux-patterns]].

### Endpoint decorators

| Decorator | Behavior | Use when |
|---|---|---|
| `Depends(require_auth)` | 401 if no valid token | Endpoint mutates user data or accesses cross-user state |
| `Depends(get_current_user)` | Returns `None` for missing/invalid token | Endpoint can serve anonymous reads OR uses ownership check via `user["user_id"]` |

Most meeting endpoints use `get_current_user` so guest mode works
without 401s — ownership is enforced via the meeting's `user_id` field.

## Storage layer

### Backing files

| File | Purpose | Owner |
|---|---|---|
| `meeting-master/data/store.json` | meetings, users, sessions | meeting-master |
| `brd-agent/backend/local_brds.json` | persisted BRD list | brd-agent |
| `.env` (repo root) | secrets (LLM key, Sarvam key, filesearch base URL) | both |

### Atomic writes

`meeting-master/backend/services/storage.py`:

- `JsonStore` class wraps file I/O.
- All writes go through `_save()` which:
  1. Acquires the RLock.
  2. Writes to `<path>.tmp` with full JSON dump.
  3. Calls `os.replace(<tmp>, <path>)` — POSIX atomic rename on Windows too.
- On corruption (JSONDecodeError), falls back to `_default_store()` and
  logs the error — never silently loses data.

### CRUD operations

```python
store.create_meeting(meeting_data) → dict
store.get_meeting(meeting_id)      → dict | None
store.update_meeting(meeting_id, partial_updates) → dict (merged)
store.list_meetings(user_id?, page, page_size, status?) → {meetings, total, page, total_pages}
store.delete_meeting(meeting_id)   → bool

store.get_user_by_id(user_id)      → dict | None
store.upsert_user(user_data)       → dict
store.get_user_stats(user_id)      → dict (counts, recent activity)
```

### Pagination

`list_meetings` uses 0-indexed slicing internally but 1-indexed `page`
parameter externally:

```python
offset = (page - 1) * page_size
end    = offset + page_size
total_pages = math.ceil(total / page_size) if total > 0 else 1
```

### Per-user team members

Stored under `users[<id>]["settings"]["team_members"]` — list of
`{name, email}` dicts. Used by AI for speaker hint matching.

`_normalize_settings_team_members` enforces:
- Strip whitespace
- Dedupe by lowercase email (when present) or name
- Drop entries with no name AND no email

## Locks & concurrency

- `JsonStore` uses an instance-level `RLock` for thread safety.
- The same instance is shared across FastAPI requests (singleton via
  `get_storage_service()`).
- Background tasks (`process_meeting_task`) acquire the same lock, so
  concurrent UI reads + background writes are safe.

## Failure modes

| Symptom | Cause |
|---|---|
| `meeting_id not found` after upload | Background task hasn't written yet; UI polled too fast |
| 403 on `generate-brd` | meeting `user_id` mismatch with authenticated user; ownership check |
| Recent meeting missing fields | Background task crashed before `_save`; check `error_message` field |
| `Auth Disabled` shown as user name in UI | Frontend should suppress this; see [[11-frontend-ux-patterns]] |

## Related skills

- [[14-schema-data-shapes]] — meeting / user dict shapes
- [[11-frontend-ux-patterns]] — AUTH_DISABLED prefill guard
- [[13-auto-dispatch-flow]] — background task that writes meeting state
