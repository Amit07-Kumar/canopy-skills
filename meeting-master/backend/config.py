import os
from pathlib import Path

# API Settings
API_TITLE = "Meeting Master API"
API_VERSION = "1.0.0"
API_DESCRIPTION = "AI-powered meeting assistant for ad-hoc workplace meetings"

# DEBUG MODE - Enables testing endpoints and verbose logging.
# Support both DEBUG_MODE and DEBUG to match local and Docker env files.
DEBUG_MODE = os.getenv("DEBUG_MODE", os.getenv("DEBUG", "true")).lower() == "true"

# Descope Auth Configuration (replaces Google OAuth)
# Auth-service validates Descope JWTs; lehana_auth library calls it automatically
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "https://auth.lehana.in")
DESCOPE_PROJECT_ID = os.getenv("DESCOPE_PROJECT_ID", "P39NXXbIdxR73iGD6sJV3EUyPFYv")
DESCOPE_FLOW_ID = "sign-up-or-in-passwords-or-social"
APP_NAME_IN_AUTH = os.getenv("APP_NAME_IN_AUTH", "meeting-master")

# JWT Configuration (still used for guest tokens)
JWT_SECRET_KEY = ""  # Set from environment
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", os.getenv("JWT_EXPIRE_HOURS", "24")))

# AI Model Configuration
DEFAULT_MODEL_PROVIDER = "openrouter"

# OpenRouter Configuration (Default AI)
OPENROUTER_API_KEY = ""  # Set from environment
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.getenv("DEFAULT_LLM_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

# Deepgram Configuration (Transcription)
DEEPGRAM_API_KEY = ""  # Set from environment

# Groq Configuration (FREE Whisper transcription - 25K seconds/month)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")  # Free at console.groq.com

# Sarvam AI Configuration (FREE - Best for Indian languages)
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")  # Free at sarvam.ai

# Default STT Provider (sarvam=Hindi, groq=multilingual, deepgram=premium)
DEFAULT_STT_PROVIDER = os.getenv("DEFAULT_STT_PROVIDER", "sarvam")

# File Upload Settings
MAX_AUDIO_SIZE_MB = 100
ALLOWED_AUDIO_FORMATS = ["wav", "mp3", "webm", "m4a", "ogg", "flac"]
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")
STORAGE_FILE_PATH = os.getenv(
    "STORAGE_FILE",
    str(Path(UPLOAD_DIR).parent / "meeting_master_store.json")
)

# Processing Settings
MAX_PROCESSING_TIME_SECONDS = 300
TRANSCRIPTION_CHUNK_SIZE = 60  # seconds

# CORS Configuration
CORS_ORIGINS = [
    "https://meeting.lehana.in",
    "https://meeting.aidhunik.com",
    "http://localhost:3000",
    "http://localhost:5000",
]

# Rate Limiting
RATE_LIMIT_PER_MINUTE = 30

# Logging - Use DEBUG in debug mode
LOG_LEVEL = "DEBUG" if DEBUG_MODE else os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# OTP/Auth bypass for testing
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() == "true"

# =============================================================================
# n8n Webhook Pipeline Configuration
# When USE_N8N_WEBHOOKS=true, the processing pipeline uses external n8n webhook
# APIs for transcription and summarization instead of the internal STT + LLM
# pipeline. This matches the integration pattern used in brd-agent.
# =============================================================================

# Feature flag: toggle between internal AI pipeline and n8n webhook pipeline
USE_N8N_WEBHOOKS = os.getenv("USE_N8N_WEBHOOKS", "true").lower() == "true"

# Webhook #1: Audio file → speaker-separated transcript
N8N_WEBHOOK_TRANSCRIBE_AUDIO = os.getenv(
    "N8N_WEBHOOK_TRANSCRIBE_AUDIO",
    "https://imworkflow.intermesh.net/webhook/transcribe-speakers"
)

# Webhook #2: Speaker transcript → MOM + Tasks + Calendar events
N8N_WEBHOOK_AI_SUMMARIZATION = os.getenv(
    "N8N_WEBHOOK_AI_SUMMARIZATION",
    "https://imworkflow.intermesh.net/webhook/AISummarization"
)

# Webhook #3: Trigger Google Calendar events + email MOM to recipients
N8N_WEBHOOK_GOOGLE_TOOLS = os.getenv(
    "N8N_WEBHOOK_GOOGLE_TOOLS",
    "https://n8n.backend.lehana.in/webhook/google_tool_event"
)

# Webhook #4: Send edited meeting email content on explicit user action
N8N_WEBHOOK_SEND_EMAIL = os.getenv(
    "N8N_WEBHOOK_SEND_EMAIL",
    "https://n8n.backend.lehana.in/webhook/google_tool_event"
)

# Timeout for webhook calls (audio transcription can be slow)
N8N_WEBHOOK_TIMEOUT = int(os.getenv("N8N_WEBHOOK_TIMEOUT", "120"))

# Cross-app bridge: Meeting Master can create BRDs in RequireWise.
BRD_AGENT_API_BASE = os.getenv("BRD_AGENT_API_BASE", "http://127.0.0.1:8025/api")
