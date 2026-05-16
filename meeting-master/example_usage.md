# Example Usage

This document provides examples of how to interact with the Meeting Master API and test cases for transcript processing.

## Transcript Processing Test Case

### Request
**Endpoint**: `POST /api/v1/meetings/process-text`
**Auth**: Bearer Token (Guest or Google)

**Body**:
```json
{
  "transcript": "Meeting with the team. Rahul will handle the API integration by Wednesday. Paras needs to review the security docs tomorrow. We will have another sync on Friday at 10 AM. Today is Sunday, February 8, 2026.",
  "title": "Debug Test Meeting"
}
```

### Expected Extracted Tasks
1. **Rahul**: API integration (Due: 2026-02-11)
2. **Paras**: Review security docs (Due: 2026-02-09)

### Expected Calendar Event
- **Sync Meeting**: Friday, Feb 13, 2026 at 10:00 AM

## API Debugging with CURL

### Guest Login
```bash
curl -X POST https://meeting.lehana.in/api/v1/auth/guest
```

### Process Text (Manual)
```bash
curl -X POST https://meeting.lehana.in/api/v1/meetings/process-text \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "Test transcript text...",
    "title": "CURL Test"
  }'
```
