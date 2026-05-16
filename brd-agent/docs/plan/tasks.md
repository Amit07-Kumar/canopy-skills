# Implementation Plan: BRD Agent

## Overview
Building a high-level frontend and backend wrapper for the BRD Agent hackathon project. The system integrates with n8n webhooks to process meeting transcripts, recordings, and task assignments, ultimately updating Business Requirements Documents (BRDs).

## Phase 1: Core Features (MVP)

- [x] 1. **Project Setup & Configuration**
  - [x] 1.1 Create `config.json` or `.env` for configurable n8n webhooks and project list.
  - [x] 1.2 Set up FastAPI backend to serve as a wrapper for n8n webhooks.
  - [x] 1.3 Set up frontend structure with Next Level Website Designer principles (Bento Grid, Glassmorphism, Animations).

- [x] 2. **Update BRDs Feature**
  - [x] 2.1 Frontend: Create a section with a dropdown for project selection (Default: "Detect Automatically", plus 5-6 options from config).
  - [x] 2.2 Frontend: Add "Update BRD" button with loading animations.
  - [x] 2.3 Backend: Create `/api/update-brd` endpoint that calls the corresponding n8n webhook.

- [x] 3. **Meeting Transcripter Feature**
  - [x] 3.1 Frontend: Create a text area to paste meeting transcriptions.
  - [x] 3.2 Frontend: Add "Generate Summary" button.
  - [x] 3.3 Backend: Create `/api/transcript-summary` endpoint calling n8n webhook.
  - [x] 3.4 Frontend: Display summary result.
  - [x] 3.5 Frontend: Show "Update BRDs" button after summary is generated, which triggers the Update BRD workflow (with project dropdown).

- [x] 4. **Meeting Recorder Feature**
  - [x] 4.1 Frontend: Create an audio recording interface (Start/Stop recording).
  - [x] 4.2 Backend: Create `/api/audio-summary` endpoint to receive audio file and send to n8n webhook.
  - [x] 4.3 Frontend: Display summary result.
  - [x] 4.4 Frontend: Show "Update BRDs" button after summary is generated.

- [x] 5. **Task Assigner Feature**
  - [x] 5.1 Frontend: Create a section to input meeting summary for task assignment.
  - [x] 5.2 Backend: Create `/api/assign-tasks` endpoint calling n8n webhook.
  - [x] 5.3 Frontend: Display assigned tasks result.

- [x] 6. **Deployment & Documentation**
  - [x] 6.1 Create Dockerfile and docker-compose.yml.
  - [x] 6.2 Configure Traefik routing for `brd.aidhunik.com` and `brd.lehana.in`.
  - [x] 6.3 Write comprehensive README.md.
  - [x] 6.4 Write MANUAL_TODO.md for n8n webhook configurations.

## Phase 2: Advanced Features

- [x] 7. **Advanced Dashboard**
  - [x] 7.1 Multi-stakeholder views (CEO, Engineering, PM).
  - [x] 7.2 Conflict detection visualization.
  - [x] 7.3 Temporal Knowledge Graph visualization.

- [x] 8. **Enhanced Integrations**
  - [x] 8.1 Direct Slack/Gmail integration from frontend.
  - [x] 8.2 Real-time collaboration on generated BRDs.
