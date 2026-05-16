# Changelog

All notable changes to Meeting Master will be documented in this file.

## [1.1] - 2026-02-03

### Added
- New `/api/v1/meetings/process-text` endpoint for immediate transcript analysis.
- `MeetingTextProcessRequest` model in `backend/models.py`.
- Summary section in the results UI to show the high-level meeting overview.
- Support for `due_date` in tasks and `meeting_id` for tracking.
- Cache busting and versioning system.
- `white-space: pre-wrap` styling for summary and email body to preserve AI formatting.

### Changed
- Refactored `transcribe` fields to `transcript_en`, `transcript_hi`, and `transcript_hinglish` for clarity and frontend alignment.
- Updated `app.js` to correctly handle `meeting.mail` instead of `mail_content`.
- Switched email body and summary rendering from `.innerHTML` to `.textContent` for safety and better plain-text handling in `contenteditable`.
- Improved AI prompt for more accurate temporal reasoning (today's date awareness).

### Fixed
- Fixed 405 Method Not Allowed error on transcript processing by implementing the missing endpoint.
- Fixed 500 Internal Server Error in guest authentication due to datetime conversion issues.
- Fixed `id` vs `meeting_id` mismatch in history and save operations.
- Fixed email body and summary not being visible due to field name mismatches and DOM property issues.

## [1.0] - 2026-02-01
- Initial release with audio recording and transcription support.
- Basic task and calendar event extraction.
- Guest mode and Google Auth support.
