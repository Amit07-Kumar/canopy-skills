# Meeting Master 🎤

**AI-Powered Meeting Intelligence Platform**

Transform your meetings into actionable outcomes with one-tap recording, multilingual transcription, and intelligent task extraction.

---

## 🚀 Quick Start

### Try It Live

**URL**: https://meeting.lehana.in

1. Login with Google (or Guest mode)
2. Click the record button
3. Speak or upload an audio file
4. Get instant transcription + tasks + calendar events + email summary

---

## ✨ Features

### 🎙️ One-Tap Recording
- Press record and start talking
- No complex setup or integrations
- Works with any meeting (in-person, phone, video)

### 🌐 Triple-Language Transcription
- **English**: Clean, formatted transcript
- **Hindi (देवनागरी)**: Full Hindi translation
- **Hinglish**: Roman transliteration

### ✅ Intelligent Task Extraction
- Auto-detects action items
- Assigns to mentioned names
- Smart deadline inference:
  - "by Friday" → Jan 31, 2026
  - "next week" → Feb 3-7, 2026
  - "end of month" → Jan 31, 2026

### 📅 Calendar Event Detection
- Recognizes scheduling discussions
- Creates complete calendar entries
- Includes attendees and descriptions

### ✉️ MoM Email Generator
- Professional format
- Key decisions highlighted
- Action items with owners
- Ready to send

### 🔑 BYOK: Bring Your Own Keys
Use your own AI API keys:
- OpenRouter (all models)
- OpenAI (GPT-4, GPT-4o)
- Google Gemini
- Groq (Llama 3.1)

---

## 📁 File Index

### 📄 Documentation Files

| File | Purpose | When to Read |
|------|---------|--------------|
| `README.md` | **START HERE** - Project overview | First stop |
| `CHANGELOG.md` | Version history and changes | Track updates |
| `example_usage.md` | Test cases and CURL examples | Debugging |
| `DESIGN.md` | Full architecture & design decisions | Deep dive |

### 💻 Backend Code Files

| File | Purpose | Key Components |
|------|---------|----------------|
| `backend/api.py` | FastAPI application | All endpoints |
| `backend/config.py` | Configuration constants | API settings |
| `backend/models.py` | Pydantic data models | Request/Response schemas |
| `backend/services/ai.py` | AI processing service | LLM prompts, processing |
| `backend/services/storage.py` | Local storage service | File-backed CRUD operations |
| `backend/version.py` | Backend version constant | Version tracking |

### 🎨 Frontend Code Files

| File | Purpose | Key Components |
|------|---------|----------------|
| `frontend/index.html` | Main HTML structure | Auth, App, Modals |
| `frontend/styles.css` | CSS design system | Variables, Responsive |
| `frontend/app.js` | JavaScript application | Recording, API calls |
| `frontend/version.js` | Frontend version constant | Cache busting |

### ⚙️ Configuration Files

| File | Purpose | What It Configures |
|------|---------|-------------------|
| `docker/docker-compose.yml` | Docker service | Container, Traefik labels |
| `docker/Dockerfile` | Container image | Python environment |
| `docker/requirements.txt` | Python deps | FastAPI, AI libs |
| `docker/.env.example` | Environment template | API keys, settings |

### 🔗 External Libraries

| Library | Path | Purpose |
|---------|------|---------|
| `stt_client.py` | `/app/lib/ai-model-calling/` | Speech-to-Text (Sarvam, Groq, Deepgram) |
| `ai_client.py` | `/app/lib/ai-model-calling/` | LLM calls (OpenRouter, Groq, etc.) |

> **Note**: The AI model calling library is mounted read-only from `/root/repo/ai-model-calling/`

---

## 🎤 Speech-to-Text (STT) Providers

Meeting Master supports multiple STT providers with automatic fallback:

| Provider | Model | Status | Best For |
|----------|-------|--------|----------|
| **Sarvam** | saarika:v2.5 | ✅ Default | Hindi, Indian languages (FREE) |
| **Groq** | whisper-large-v3 | Optional | English, Fast (FREE tier) |
| **Deepgram** | nova-2 | Optional | High accuracy (Paid) |

### Configuration

```bash
# In .env file
SARVAM_API_KEY=sk_xxx          # FREE - best for Indian languages
DEFAULT_STT_PROVIDER=sarvam    # sarvam | groq | deepgram

# Optional fallbacks
GROQ_API_KEY=gsk_xxx           # FREE tier available
DEEPGRAM_API_KEY=xxx           # Paid
```

### Testing STT

```bash
# Test transcription endpoint
curl -X POST "https://meeting.lehana.in/api/v1/debug/transcribe" \
  -F "audio=@meeting.m4a" \
  -F "language=hi"

# Check STT configuration
curl "https://meeting.lehana.in/api/v1/debug/config" | jq '.stt_config'
```

---

## 🛠️ Installation

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- API Keys: Sarvam (free), OpenRouter (or BYOK)

### Local Development

```bash
# Clone to ideas directory
cd /root/ideas/meeting-master

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r docker/requirements.txt

# Set up environment
cp docker/.env.example .env
# Edit .env with your API keys

# Run the server
cd backend
uvicorn api:app --reload --host 0.0.0.0 --port 5088
```

### Docker Deployment

```bash
# Navigate to docker config
cd /root/docker/meeting-master

# Copy environment file
cp .env.example .env
# Edit .env with your API keys

# Deploy
docker-compose up -d

# Verify
curl https://meeting.lehana.in/health
```

---

## 🔌 API Reference

### Authentication

```bash
# Login with Google
POST /api/v1/auth/google
Content-Type: application/json
{
  "token": "google_oauth_token"
}

# Response
{
  "access_token": "jwt_token",
  "user": { "id": "...", "name": "...", "email": "..." }
}
```

### Process Meeting

```bash
# Upload and process audio
POST /api/v1/meetings
Authorization: Bearer {jwt_token}
Content-Type: multipart/form-data

file: [audio file]
title: "Weekly Standup" (optional)

# Response
{
  "id": "meeting_uuid",
  "title": "Weekly Standup",
  "transcriptions": {
    "english": "...",
    "hindi": "...",
    "hinglish": "..."
  },
  "tasks": [
    {
      "id": "task_uuid",
      "description": "Complete report",
      "assignee": "John",
      "deadline": "2026-01-31",
      "priority": "high",
      "completed": false
    }
  ],
  "calendar_events": [
    {
      "id": "event_uuid",
      "title": "Review Meeting",
      "datetime": "2026-02-04T14:00:00",
      "duration_minutes": 60,
      "attendees": ["John", "Sarah"],
      "description": "Review Q1 progress"
    }
  ],
  "mom_email": {
    "subject": "MoM: Weekly Standup - Jan 28, 2026",
    "body": "..."
  }
}
```

### List Meetings

```bash
GET /api/v1/meetings
Authorization: Bearer {jwt_token}

# Query params
?page=1&limit=10&search=keyword
```

### Update Meeting

```bash
PUT /api/v1/meetings/{meeting_id}
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "title": "Updated Title",
  "tasks": [...],
  "calendar_events": [...]
}
```

### User Settings

```bash
# Get settings
GET /api/v1/settings
Authorization: Bearer {jwt_token}

# Update settings (BYOK keys)
PUT /api/v1/settings
{
  "ai_provider": "openai",
  "api_keys": {
    "openai": "sk-..."
  }
}
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (PWA)                           │
│  ┌─────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  Auth   │  │  Recording   │  │  Results Display       │ │
│  └────┬────┘  └──────┬───────┘  └──────────┬─────────────┘ │
└───────┼──────────────┼─────────────────────┼────────────────┘
        │              │                     │
        ▼              ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                          │
│  ┌─────────────┐  ┌────────────┐  ┌────────────────────┐   │
│  │ Auth API    │  │ Meeting API│  │ Settings API       │   │
│  └──────┬──────┘  └─────┬──────┘  └─────────┬──────────┘   │
└─────────┼───────────────┼───────────────────┼───────────────┘
          │               │                   │
          ▼               ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    Services Layer                           │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐    │
│  │ Local JSON   │  │ Deepgram STT │  │ LLM (AI)       │    │
│  │ Storage      │  │ (Transcribe) │  │ (Analyze)      │    │
│  └──────────────┘  └──────────────┘  └────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPGRAM_API_KEY` | Yes | Deepgram speech-to-text API key |
| `OPENROUTER_API_KEY` | No* | OpenRouter API key (default AI) |
| `GOOGLE_CLIENT_ID` | Yes | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | Google OAuth client secret |
| `JWT_SECRET` | Yes | JWT signing secret |

*Required if not using BYOK

---

## 🧪 Testing

**Status**: ✅ **28/28 Tests Passing (100%)**

### Test Documentation

| Document | Purpose |
|----------|---------|
| [TEST_GUIDE.md](tests/TEST_GUIDE.md) | Comprehensive testing guide with curl examples |
| [TEST_RESULTS.md](tests/TEST_RESULTS.md) | Complete test results with actual responses |

### Test Categories

| Category | Tests | Status |
|----------|-------|--------|
| Authentication | 3 | ✅ All passing |
| Upload & Processing | 5 | ✅ All passing |
| Debug Endpoints | 3 | ✅ All passing |
| Edge Cases | 4 | ✅ All passing |
| BYOK Settings | 3 | ✅ All passing |
| Meeting Status | 2 | ✅ All passing |
| Meeting List | 2 | ✅ All passing |
| Meeting Delete | 2 | ✅ All passing |
| Frontend Landing | 2 | ✅ All passing |
| Dual Domain | 2 | ✅ All passing |

### Quick Testing

```bash
# Health check (both domains work)
curl https://meeting.lehana.in/health
curl https://meeting.aidhunik.com/health

# Get guest token
TOKEN=$(curl -s -X POST "https://meeting.lehana.in/api/v1/auth/guest" | jq -r '.access_token')

# Test with sample audio
curl -X POST "https://meeting.lehana.in/api/v1/meetings/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "transcript=John should complete the report by Friday. Let's meet next Tuesday at 2 PM."
```

### Test Scenarios

1. **Basic Recording**: Record 30 seconds, verify transcription
2. **Task Detection**: Say "John should complete the report by Friday"
3. **Calendar Detection**: Say "Let's meet next Tuesday at 2 PM"
4. **Hindi/Hinglish**: Mix languages in recording
5. **BYOK**: Test with your own OpenRouter/OpenAI keys

---

## 📈 Roadmap

- [x] MVP: Recording, transcription, tasks, calendar, email
- [x] BYOK: Support for multiple AI providers
- [ ] Google Calendar integration
- [ ] Slack/Teams integration
- [ ] Speaker diarization
- [ ] Mobile apps

---

## 🤝 Contributing

Contributions welcome! Please read the DESIGN.md for architecture understanding.

---

## 📄 License

MIT License - See LICENSE file

---

## 📞 Support

- **Issues**: GitHub Issues
- **Email**: paras@lehana.in
- **Demo**: https://meeting.lehana.in

---

**Version**: 1.1.0  
**Last Updated**: February 3, 2026  
**Tests**: 28/28 Passing ✅
