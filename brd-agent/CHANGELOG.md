# Changelog
All notable changes to the RequireWise project will be documented in this file.

## [1.5] - 2026-02-22

### Fixed
- Replaced the stringified dictionary `summary` property from the auto-filling logic of the Task Assigner with the raw transcriber text (or speaker key-value pairs). This prevents the UI from populating `"• {'topic': '...'}"` into text input boxes when using the Live Audio or Transcipt analysis fields.

## [1.4] - 2026-02-22

### Fixed
- Fixed UI rendering parsing issues where properties `event_title` and `event_date` sent from the transcription API were not mapped correctly on the Calendar, resulting in "undefined — undefined" displaying on the frontend UI. The UI now gracefully extracts those attributes or falls back to legacy field names appropriately.

## [1.3] - 2026-02-22

### Fixed
- Hardcoded specific recipient email list instead of sending an empty `[]` array when requesting Google Tools (/api/google-tools) to send tasks inside the Task Assigner tool.

## [1.2] - 2026-02-22

### Fixed
- Fixed object rendering issue in the frontend where Minutes of Meeting (MOM) and Tasks arrays returning embedded objects resulted in `[object Object]` displaying on the UI. The lists now correctly parse nested attributes and show proper descriptions.

## [1.1] - 2026-02-21

### Added
- **Chat Integration Logic**: Implemented the diff engine in `playground.js` to correctly merge chat context into generated BRDs.
- **Mock Data Fallbacks**: Added fallback handlers in `backend/server.py` to ensure the application remains functional even if n8n workflows return 500 errors.
- **Version Tracking**: Added `version.js` and cache busting in `index.html`.
- **E2E Test Suite**: Conducted full end-to-end testing via browser automation.

### Changed
- **Dashboard Maintenance**: Fixed several TypeErrors during data loading (standardized `activity-feed` and KPI metrics IDs).
- **Playground UX**: Improved Step 1 → Step 2 transition state handling.
- **Architecture**: Switched to a "Robust Demo" mode where local mock data is preferred if upstream services fail.

### Fixed
- Fixed "Integrating chat into brd is not working" issue by implementing real diff application in the frontend.
- Fixed D3 Knowledge Graph rendering issue when tab was switched.
- Fixed `TypeError: Cannot set properties of null` at `loadDashboardData`.

---

## [1.0] - Early 2026
- Initial release with Core Features (Phase 1).
- n8n integration for transcript analysis.
- Basic Advanced Dashboard shell.
