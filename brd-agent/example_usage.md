# RequireWise — Example Usage & API Guide

This document provides example requests for testing the RequireWise API endpoints and UI flows.

## API Endpoints (Local Testing)

### 1. Update BRD
Triggers the requirement synchronization workflow.
```bash
curl -X POST http://localhost:8025/api/update-brd \
     -H "Content-Type: application/json" \
     -d '{"project": "Detect Automatically", "instruction": "Add a new module for real-time monitoring"}'
```

### 2. Transcript Summary
Extracts MOM and tasks from meeting text.
```bash
curl -X POST http://localhost:8025/api/transcript-summary \
     -H "Content-Type: application/json" \
     -d '{"title": "Sync Meeting", "transcript": "John: We need to fix the login bug. Sarah: I will handle it by Monday."}'
```

### 3. Generate BRD from Email
Used in the Playground to convert a single email into a full document.
```bash
curl -X POST http://localhost:8025/api/generate-brd-from-email \
     -H "Content-Type: application/json" \
     -d '{"email_id": "email-1", "transcript": "Infrastructure improvements required for Pine Ave", "title": "Pine Ave Project"}'
```

## UI Testing Flows

### Playground Integration Test
1. Naviate to **🧪 Playground**.
2. Select **Pine Avenue Infrastructure** card.
3. Click **Generate BRD from Email**.
4. Once generated, **Step 2** will appear.
5. Select **Functional Requirements Discussion** (Chat).
6. Click **Integrate Chat into BRD**.
7. Observe the green highlights in the Diff view and the updated BRD content.

### Dashboard Verification
1. Navigate to **Advanced Dashboard**.
2. Verify **KPI Bar** shows numbers (not undefined).
3. Switch to **Knowledge Graph** tab and verify the D3 network renders.
4. Click a node to see the **Evolution History** panel update.
