# Manual Configuration Checklist

This document outlines the manual steps required to fully configure the BRD Agent system, specifically focusing on the n8n workflows that power the backend logic.

## Phase 1: Core Features

### 1. Configure n8n Webhooks
The backend relies on four specific n8n webhooks. You need to create these workflows in your n8n instance and update the `.env` file in `backend/` with the correct URLs.

- [ ] **Update BRD Workflow**
  - **Trigger**: Webhook (POST)
  - **Input**: `{"project": "Project Name", "summary": "Optional context"}`
  - **Action**: Generate/Update BRD document based on the project and summary.
  - **Output**: `{"status": "success", "message": "BRD updated"}`
  - **Update `.env`**: `N8N_WEBHOOK_UPDATE_BRD=your_webhook_url`

- [ ] **Transcript Summary Workflow**
  - **Trigger**: Webhook (POST)
  - **Input**: `{"transcript": "Raw meeting text..."}`
  - **Action**: Use an LLM (e.g., Gemini/Claude) to extract key decisions, requirements, and action items.
  - **Output**: `{"summary": "Extracted insights..."}`
  - **Update `.env`**: `N8N_WEBHOOK_TRANSCRIPT_SUMMARY=your_webhook_url`

- [ ] **Audio Summary Workflow**
  - **Trigger**: Webhook (POST, Multipart Form Data)
  - **Input**: Audio file (`file` field)
  - **Action**: Transcribe audio (e.g., using Whisper) and then summarize using an LLM.
  - **Output**: `{"summary": "Extracted insights from audio..."}`
  - **Update `.env`**: `N8N_WEBHOOK_AUDIO_SUMMARY=your_webhook_url`

- [ ] **Task Assigner Workflow**
  - **Trigger**: Webhook (POST)
  - **Input**: `{"summary": "Meeting summary text..."}`
  - **Action**: Use an LLM to extract actionable tasks and assignees.
  - **Output**: `{"tasks": ["Task 1", "Task 2"]}`
  - **Update `.env`**: `N8N_WEBHOOK_ASSIGN_TASKS=your_webhook_url`

### 2. Configure Projects
- [ ] Open `backend/config.json` and update the `projects` array with your actual project names. The first option should remain "Detect Automatically".

## Phase 2: Advanced Features

### 3. Configure Advanced Webhooks
Update the `.env` file with the following webhooks for the Advanced Dashboard features:

- [ ] **Dashboard Data Workflow**
  - **Trigger**: Webhook (POST)
  - **Input**: `{"project": "Project Name"}`
  - **Action**: Fetch metrics and recent activity for the project.
  - **Output**: `{"metrics": {"completion": 75, "conflicts": 2, "stakeholders": 5}, "recent_activity": ["Activity 1", "Activity 2"]}`
  - **Update `.env`**: `N8N_WEBHOOK_DASHBOARD_DATA=your_webhook_url`

- [ ] **Conflict Detection Workflow**
  - **Trigger**: Webhook (POST)
  - **Input**: `{"project": "Project Name"}`
  - **Action**: Analyze project data for conflicts.
  - **Output**: `{"conflicts": [{"type": "Timeline", "description": "...", "severity": "High"}]}`
  - **Update `.env`**: `N8N_WEBHOOK_CONFLICT_DETECTION=your_webhook_url`

- [ ] **Knowledge Graph Workflow**
  - **Trigger**: Webhook (POST)
  - **Input**: `{"project": "Project Name"}`
  - **Action**: Generate graph data representing requirements and dependencies.
  - **Output**: `{"graph": {"nodes": [...], "edges": [...]}}`
  - **Update `.env`**: `N8N_WEBHOOK_KNOWLEDGE_GRAPH=your_webhook_url`

- [ ] **Slack Integration Workflow**
  - **Trigger**: Webhook (POST)
  - **Input**: `{"project": "Project Name"}`
  - **Action**: Trigger data sync from Slack for the project.
  - **Output**: `{"message": "Sync started"}`
  - **Update `.env`**: `N8N_WEBHOOK_SLACK_INTEGRATION=your_webhook_url`

- [ ] **Gmail Integration Workflow**
  - **Trigger**: Webhook (POST)
  - **Input**: `{"project": "Project Name"}`
  - **Action**: Trigger data sync from Gmail for the project.
  - **Output**: `{"message": "Sync started"}`
  - **Update `.env`**: `N8N_WEBHOOK_GMAIL_INTEGRATION=your_webhook_url`

## 🚨 Critical Format Requirements

### n8n Response Wrapping
The FastAPI backend (`server.py`) expects n8n webhooks to return results wrapped in a JSON array:
- **Correct Output**: `[ { "summary": "...", "tasks": [...] } ]`
- **Incorrect Output**: `{ "summary": "...", "tasks": [...] }`

If you do not wrap the response in an array, the proxy will fail to parse the speaker map correctly.

### Fallback Mechanism
The backend now includes a robust **Mock Fallback** mechanism. If n8n returns a `500` error or if the connection fails, the application will provide sample data from the `Pine Avenue` dataset. This ensures the UI is always testable even if the workflows are offline.

