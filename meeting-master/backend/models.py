"""
Meeting Master - Pydantic Models

Defines all data models for:
- API requests/responses
- Database documents
- AI processing outputs
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum


# =============================================================================
# Enums
# =============================================================================

class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TaskCategory(str, Enum):
    # Legacy values
    BUG = "BUG"
    FEATURE = "FEATURE"
    DOCUMENTATION = "DOCUMENTATION"
    MEETING = "MEETING"
    OTHER = "OTHER"
    # AI Scrum Assistant (n8n AISummarization) emits these six. Keep them
    # accepted so the meeting record round-trips through Pydantic cleanly.
    DEVELOPMENT = "DEVELOPMENT"
    RESEARCH = "RESEARCH"
    INFRA = "INFRA"
    OPS = "OPS"


class TaskStatus(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class ModelProvider(str, Enum):
    OPENROUTER = "openrouter"
    OPENAI = "openai"
    GEMINI = "gemini"
    GROQ = "groq"


class CalendarEventType(str, Enum):
    MEETING = "MEETING"
    REMINDER = "REMINDER"
    DEADLINE = "DEADLINE"


# =============================================================================
# Authentication Models
# =============================================================================

class GoogleAuthRequest(BaseModel):
    """Request body for Google OAuth"""
    credential: str = Field(..., description="Google OAuth credential token")


class TokenResponse(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserProfile"


class UserProfile(BaseModel):
    """User profile information"""
    user_id: str
    email: Optional[str] = None  # Optional for guest users
    name: str
    picture_url: Optional[str] = None
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None


# =============================================================================
# Settings Models
# =============================================================================

class SettingsTeamMember(BaseModel):
    """Lightweight teammate record used in workspace settings"""
    name: str
    email: Optional[str] = None


class UserSettings(BaseModel):
    """User-facing workspace settings"""
    profile_name: str = ""
    profile_email: str = ""
    default_language: str = "en"
    speaker_diarization: bool = True
    team_members: List[SettingsTeamMember] = Field(default_factory=list)


class UserSettingsUpdate(BaseModel):
    """Partial update for workspace settings"""
    profile_name: Optional[str] = None
    profile_email: Optional[str] = None
    default_language: Optional[str] = None
    speaker_diarization: Optional[bool] = None
    team_members: Optional[List[SettingsTeamMember]] = None


# =============================================================================
# Team Models
# =============================================================================

class TeamMember(BaseModel):
    """Team member information"""
    name: str
    email: EmailStr
    added_at: datetime = Field(default_factory=datetime.utcnow)


class TeamMemberCreate(BaseModel):
    """Create new team member"""
    name: str
    email: EmailStr


# =============================================================================
# Meeting Models
# =============================================================================

class Attendee(BaseModel):
    """Meeting attendee identified from transcription"""
    speaker_id: str = Field(..., description="e.g., SPEAKER_1, SPEAKER_2")
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    identified: bool = False
    hint: Optional[str] = Field(None, description="Context about identification")


class Task(BaseModel):
    """Action item extracted from meeting"""
    id: str
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    category: TaskCategory = TaskCategory.OTHER
    status: TaskStatus = TaskStatus.TODO
    due_date: Optional[date] = None
    deadline_source: Optional[str] = Field(None, description="How deadline was determined")
    dependencies: List[str] = []
    context: Optional[str] = None


class CalendarEvent(BaseModel):
    """Calendar event to be created"""
    id: str
    title: str
    description: Optional[str] = None
    start_datetime: datetime
    end_datetime: datetime
    attendees: List[str] = []  # List of emails
    source: Optional[str] = Field(None, description="How event was identified")
    type: CalendarEventType = CalendarEventType.MEETING
    google_event_id: Optional[str] = None  # After creation


class MailContent(BaseModel):
    """Email content for Minutes of Meeting"""
    subject: str
    to: List[str]  # Can be emails or names - will be resolved later
    cc: List[str] = []  # Can be emails or names - will be resolved later
    body: str
    sent: bool = False
    sent_at: Optional[datetime] = None


class MeetingEmailSendRequest(BaseModel):
    """Request body for triggering the email delivery webhook"""
    subject: str
    to: str = Field(..., description="Comma-separated list of recipient email addresses")
    body: str
    cc: List[str] = []


# =============================================================================
# Meeting Document
# =============================================================================

class MeetingCreate(BaseModel):
    """Create new meeting (manual transcript input)"""
    title: Optional[str] = None
    transcript: Optional[str] = Field(None, description="Manual transcript input")
    attendee_emails: List[EmailStr] = []


class MeetingTextProcessRequest(BaseModel):
    """Request to process a literal transcript text"""
    transcript: str
    speaker_hints: List[str] = []
    title: Optional[str] = None
    attendee_emails: List[EmailStr] = []
    participants: List[str] = []


class MeetingProcessRequest(BaseModel):
    """Request to process a meeting"""
    language_hint: Optional[str] = None  # Hint about primary language


class MeetingAutomationStatus(BaseModel):
    """Workflow automation status for dispatching follow-up actions"""
    dispatch_success: bool = False
    auto_sent_email: bool = False
    auto_scheduled_calendar: bool = False
    dispatched_at: Optional[datetime] = None
    baseline_timestamp: Optional[datetime] = None
    recipients: List[str] = []
    source: Optional[str] = None
    error: Optional[str] = None


class MeetingKPI(BaseModel):
    """Execution intelligence metrics derived from a meeting"""
    execution_health_index: float = 0
    context_completeness_score: float = 0
    action_leakage_rate: float = 0
    closure_rate: float = 0
    time_to_action_seconds: Optional[float] = None
    ownership_coverage: float = 0
    due_date_coverage: float = 0
    priority_clarity_rate: float = 0
    calendar_coverage: float = 0
    task_context_coverage: float = 0
    detected_commitments: int = 0
    task_count: int = 0
    calendar_count: int = 0
    recipient_count: int = 0
    email_ready: bool = False
    auto_dispatch_success: bool = False
    missing_fields: List[str] = Field(default_factory=list)
    generated_at: Optional[datetime] = None


class KPIOverview(BaseModel):
    """Portfolio view of execution KPIs across meetings"""
    total_meetings: int = 0
    processed_meetings: int = 0
    execution_health_index: float = 0
    context_completeness_score: float = 0
    action_leakage_rate: float = 0
    closure_rate: float = 0
    time_to_action_seconds: Optional[float] = None
    automation_coverage: float = 0
    high_risk_meetings: int = 0


class Meeting(BaseModel):
    """Complete meeting document"""
    meeting_id: str
    user_id: str
    title: Optional[str] = None
    date: datetime
    duration_seconds: Optional[int] = None
    audio_url: Optional[str] = None
    status: ProcessingStatus = ProcessingStatus.PENDING
    
    # Transcriptions
    raw_transcript: Optional[str] = None
    transcript_en: Optional[str] = None  # Clean English
    transcript_hi: Optional[str] = None  # Hindi (Devanagari)
    transcript_hinglish: Optional[str] = None  # Hinglish (English script)
    
    # Extracted data
    attendees: List[Attendee] = []
    tasks: List[Task] = []
    calendar_events: List[CalendarEvent] = []
    mail: Optional[MailContent] = None
    kpis: Optional[MeetingKPI] = None
    automation: Optional[MeetingAutomationStatus] = None
    
    # Metadata
    summary: Optional[str] = None
    tags: List[str] = []
    sentiment: Optional[str] = None
    confidence: Optional[float] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None
    
    # Processing info
    model_used: Optional[str] = None
    processing_time_seconds: Optional[float] = None
    error_message: Optional[str] = None
    processing_stage: Optional[str] = None
    processing_message: Optional[str] = None
    processing_progress: Optional[int] = None


class MeetingUpdate(BaseModel):
    """Update meeting (edits from frontend)"""
    title: Optional[str] = None
    transcript_en: Optional[str] = None
    transcript_hi: Optional[str] = None
    transcript_hinglish: Optional[str] = None
    attendees: Optional[List[Attendee]] = None
    tasks: Optional[List[Task]] = None
    calendar_events: Optional[List[CalendarEvent]] = None
    mail: Optional[MailContent] = None
    tags: Optional[List[str]] = None
    kpis: Optional[MeetingKPI] = None
    automation: Optional[MeetingAutomationStatus] = None


class MeetingListItem(BaseModel):
    """Meeting item for list view"""
    meeting_id: str
    title: Optional[str]
    date: datetime
    duration_seconds: Optional[int]
    status: ProcessingStatus
    summary: Optional[str]
    task_count: int = 0
    attendee_count: int = 0


class MeetingListResponse(BaseModel):
    """Paginated meeting list"""
    meetings: List[MeetingListItem]
    total: int
    page: int
    limit: int
    has_more: bool


# =============================================================================
# AI Processing Models
# =============================================================================

class TranscriptionResult(BaseModel):
    """Result from transcription service"""
    raw_text: str
    language_detected: Optional[str] = None
    confidence: Optional[float] = None
    speakers: Optional[List[Dict[str, Any]]] = None
    duration_seconds: Optional[float] = None


class AIProcessingResult(BaseModel):
    """Complete AI processing result"""
    transcript_en: str
    transcript_hi: str
    transcript_hinglish: str
    attendees: List[Attendee]
    tasks: List[Task]
    calendar_events: List[CalendarEvent]
    mail: MailContent
    summary: str
    tags: List[str]
    sentiment: str
    confidence: float


class ProcessingStatusResponse(BaseModel):
    """Response for processing status check"""
    meeting_id: str
    status: ProcessingStatus
    progress: Optional[int] = None  # 0-100 percentage
    stage: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# Calendar Integration Models
# =============================================================================

class CalendarAuthURL(BaseModel):
    """Google Calendar authorization URL"""
    auth_url: str


class CalendarEventCreate(BaseModel):
    """Request to create calendar events"""
    meeting_id: str
    event_ids: List[str]  # IDs of events to create from meeting


class CalendarEventResult(BaseModel):
    """Result of calendar event creation"""
    event_id: str
    google_event_id: str
    success: bool
    error: Optional[str] = None


# =============================================================================
# API Response Models
# =============================================================================

class HealthResponse(BaseModel):
    """Health check response — follows /root/.github/instructions/health_endpoint.instructions.md"""
    status: str = "ok"
    started: str
    host: str
    version: str


class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None


class SuccessResponse(BaseModel):
    """Generic success response"""
    success: bool = True
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


# Forward references
TokenResponse.model_rebuild()
