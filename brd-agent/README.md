# RequireWise - Intelligent BRD Agent
**Version**: 1.5

RequireWise is an AI-powered Business Requirements Intelligence Platform that transforms scattered conversations into executable Business Requirements Documents (BRDs).

## 📁 File Index

### 📄 Documentation Files
| File | Purpose | When to Read |
|------|---------|--------------|
| `README.md` | **START HERE** - Project overview | First stop for understanding |
| `PITCH.md` | Pitch Document | For investors, stakeholders, and hackathons |
| `pitch.txt` | Plain Text Pitch | For quick copy-pasting into forms/emails |
| `CHANGELOG.md` | Version history | Check for recent updates |
| `example_usage.md` | API & UI test cases | For developers/testers |
| `MANUAL_TODO.md` | n8n Config checklist | To setup background logic |

### 💻 Backend Code Files
| File | Purpose | Key Functions/Classes |
|------|---------|----------------------|
| `backend/server.py` | FastAPI Proxy Server | `/api/*` endpoints + Mock Fallback |
| `backend/config.json` | Project configuration | List of active BRD projects |

### 🎨 Frontend Code Files
| File | Purpose | Key Components |
|------|---------|----------------|
| `frontend/index.html` | Page structure | Bento Layout, Modern UI |
| `frontend/script.js` | Core UI Logic | Tab handling, Core API calls |
| `frontend/dashboard.js` | Advanced Analytics | D3 Knowledge Graph, Conflicts |
| `frontend/playground.js` | E2E Simulation | Email → BRD → Chat Integration |
| `frontend/version.js` | Version tracking | Cache busting constant |

### ⚙️ Configuration Files
| File | Purpose | What It Configures |
|------|---------|-------------------|
| `backend/.env` | Webhook URLs | n8n integration points |
| `backend/requirements.txt` | Dependencies | FastAPI, httpx, etc. |

## Features
- **Update BRDs**: Select a project and update its BRD based on recent context.
- **Meeting Transcripter**: Paste raw meeting transcripts to extract key decisions and requirements.
- **Meeting Recorder**: Record live audio to extract insights.
- **Task Assigner**: Generate actionable tasks from meeting summaries.
- **Advanced Dashboard**: Visual conflict resolution and Knowledge Graph (D3.js).
- **Playground**: End-to-end simulation of the requirement extraction pipeline.

## Architecture
- **Frontend**: HTML5, Vanilla JS, CSS3 (Tailwind) with Glassmorphism.
- **Backend**: FastAPI (Python) with fallback mock data for robust demos.
- **Intelligence**: Powered by n8n workflows (see `MANUAL_TODO.md`).


## Quick Start

1. Clone the repository.
2. Configure the `.env` file in `backend/` with your n8n webhook URLs.
3. Configure the `config.json` in `backend/` with your project names.
4. Run with Docker Compose:
   ```bash
   docker-compose -f docker/brd-agent/docker-compose.yml up -d --build
   ```

## API Reference
- `GET /health`: Health check endpoint.
- `GET /api/config`: Get frontend configuration (projects).
- `POST /api/update-brd`: Trigger BRD update workflow.
- `POST /api/transcript-summary`: Generate summary from transcript.
- `POST /api/audio-summary`: Generate summary from audio file.
- `POST /api/assign-tasks`: Generate tasks from summary.
