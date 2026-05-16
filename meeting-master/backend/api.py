"""
Meeting Master - Main FastAPI Application

AI-powered meeting assistant for ad-hoc workplace meetings.
One tap to record, automatic transcription, intelligent task extraction,
calendar booking, and MoM distribution.
"""

import os
import ast
import json
import uuid
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

import httpx
import pytz
from pydantic import BaseModel

# Capture startup time in IST for health endpoint (per health_endpoint.instructions.md)
_IST = pytz.timezone('Asia/Kolkata')
STARTED_AT = datetime.now(_IST).strftime("%b %d, %Y at %I:%M %p IST")

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, BackgroundTasks, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from jose import JWTError, jwt

# Use relative imports when running as a package
try:
    from . import config
    from .auth import require_auth, get_current_user
    from .models import (
        TokenResponse, UserProfile, UserSettings, UserSettingsUpdate,
        TeamMember, TeamMemberCreate, Meeting, MeetingCreate, MeetingUpdate,
        MeetingListResponse, MeetingProcessRequest, MeetingTextProcessRequest,
        MeetingEmailSendRequest, KPIOverview,
        ProcessingStatusResponse,
        CalendarAuthURL, CalendarEventCreate, CalendarEventResult,
        HealthResponse, ErrorResponse, SuccessResponse,
        ProcessingStatus, ModelProvider
    )
    from .services.storage import get_storage_service
    from .services.ai import get_ai_service
    from .services.kpi import compute_meeting_kpis, compute_portfolio_kpis
    from .services.webhook import (
        transcribe_audio_webhook,
        summarize_transcript_webhook,
        trigger_google_tools_webhook,
        trigger_email_send_webhook,
        map_webhook_to_meeting_updates,
    )
except ImportError:
    # Fallback for direct execution
    import config
    from auth import require_auth, get_current_user
    from models import (
        TokenResponse, UserProfile, UserSettings, UserSettingsUpdate,
        TeamMember, TeamMemberCreate, Meeting, MeetingCreate, MeetingUpdate,
        MeetingListResponse, MeetingProcessRequest, MeetingTextProcessRequest,
        MeetingEmailSendRequest, KPIOverview,
        ProcessingStatusResponse,
        CalendarAuthURL, CalendarEventCreate, CalendarEventResult,
        HealthResponse, ErrorResponse, SuccessResponse,
        ProcessingStatus, ModelProvider
    )
    from services.storage import get_storage_service
    from services.ai import get_ai_service
    from services.kpi import compute_meeting_kpis, compute_portfolio_kpis
    from services.webhook import (
        transcribe_audio_webhook,
        summarize_transcript_webhook,
        trigger_google_tools_webhook,
        trigger_email_send_webhook,
        map_webhook_to_meeting_updates,
    )


# Configure logging
logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
    description=config.API_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create upload directory
UPLOAD_DIR = Path(config.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Dependencies
# =============================================================================

def get_store():
    """Get the local persistence service."""
    return get_storage_service()


def ensure_user_record(user: Optional[dict], store=None) -> Optional[dict]:
    """Create a minimal persisted user record on first access."""
    if not user:
        return None

    store = store or get_store()
    user_id = user.get("user_id") or user.get("id")
    if not user_id:
        return None

    existing = store.get_user_by_id(user_id)
    if existing:
        return existing

    now = datetime.utcnow().isoformat()
    return store.create_user({
        "user_id": user_id,
        "email": user.get("email", ""),
        "name": user.get("name", "User"),
        "created_at": now,
        "last_login": now,
        "settings": {},
        "team_members": [],
        "is_guest": user.get("is_guest", False),
    })


def _normalize_settings_team_members(members: Optional[List[dict]]) -> List[dict]:
    normalized_members = []

    for member in members or []:
        if not isinstance(member, dict):
            continue

        name = str(member.get("name", "")).strip()
        email = str(member.get("email", "")).strip()

        if not name:
            continue

        normalized_members.append({
            "name": name,
            "email": email or None,
        })

    return normalized_members


def _resolve_user_team_members(user_data: Optional[dict]) -> List[dict]:
    if not user_data:
        return []

    settings = dict(user_data.get("settings") or {})
    return _normalize_settings_team_members(
        settings.get("team_members") or user_data.get("team_members") or []
    )


def _fallback_process_transcript(
    transcript: str,
    meeting_date: datetime,
    title: str,
    participants: Optional[List[str]] = None,
) -> dict:
    """
    Simple keyword-based fallback when n8n webhooks are unavailable.
    Extracts tasks using action-verb patterns and builds a basic MOM/summary.
    No API keys required — always works offline.
    """
    import re

    participant_names = [name.strip() for name in (participants or []) if str(name or '').strip()]
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', transcript) if s.strip()]
    ACTION_WORDS = (
        r'\b(will|needs? to|should|must|going to|is going to|has to|'
        r'is responsible for|agreed to|shall|plans? to|decided to|committed to|'
        r'please|review|share|send|update|schedule|set|call|approve|approval|book|booking|calendar|event|ticket|'
        r'kar do|kar dena|karna hai|karna hoga|bhej dungi|bhej dega|bhej do|'
        r'set kar do|review kar lo|dekh lo|chahiye|बुक|बुक करो|बुक कर दो|कैलेंडर|इवेंट|टिकट)\b'
    )
    task_sentences = [s for s in sentences if re.search(ACTION_WORDS, s, re.IGNORECASE)]

    def _extract_assignee(sentence: str) -> Optional[str]:
        if re.search(r'\b(someone|koi|team)\b', sentence, re.IGNORECASE):
            return None

        speaker_match = re.match(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*:\s*(.*)$', sentence)
        if speaker_match:
            speaker_name = speaker_match.group(1)
            body = speaker_match.group(2).strip()
            direct_target = re.match(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*,', body)
            if direct_target:
                return direct_target.group(1)
            if re.search(r'\b(i|i\'ll|i will|main|mai)\b', body, re.IGNORECASE):
                return speaker_name
            if re.search(r'\b(someone|koi|team)\b', body, re.IGNORECASE):
                return None
            return speaker_name

        lead_name = re.match(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*,', sentence)
        if lead_name:
            return lead_name.group(1)

        said_subject = re.match(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s+said\b', sentence, re.IGNORECASE)
        if said_subject:
            return said_subject.group(1)

        subject_name = re.match(
            r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b.*\b(?:will|should|needs? to|must|committed to|said he will|said she will|bhej dungi|bhej dega|kar do|update|schedule|set)\b',
            sentence,
            re.IGNORECASE,
        )
        if subject_name:
            return subject_name.group(1)

        for participant in participant_names:
            if re.search(rf'^\s*{re.escape(participant)}\b', sentence):
                return participant
            if re.search(rf'\b{re.escape(participant)}\b\s*(?:,|please|tum|aap)', sentence, re.IGNORECASE):
                return participant

        assignee_match = re.match(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)', sentence)
        return assignee_match.group(1) if assignee_match else None

    def _extract_deadline_hint(sentence: str) -> Optional[str]:
        deadline_match = re.search(
            r'\b(kal tak|kal|aaj|aaj tak|shaam tak|subah tak|raat tak|'
            r'today|tomorrow|this evening|tonight|next week|by friday|by thursday|'
            r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
            r'\d{1,2}\s*(?:baje|am|pm)|\d{1,2}[\/\-]\d{1,2})\b',
            sentence,
            re.IGNORECASE,
        )
        return deadline_match.group(0).strip() if deadline_match else None

    def _resolve_relative_due_date(sentence: str) -> Optional[str]:
        lower = sentence.lower()
        target_date = None
        if 'tomorrow' in lower or 'kal' in lower:
            target_date = meeting_date + timedelta(days=1)
        elif 'today' in lower or re.search(r'\baaj\b', lower):
            target_date = meeting_date
        elif 'friday' in lower:
            target_date = meeting_date + timedelta(days=(4 - meeting_date.weekday()) % 7 or 7)
        elif 'thursday' in lower:
            target_date = meeting_date + timedelta(days=(3 - meeting_date.weekday()) % 7 or 7)
        return target_date.date().isoformat() if target_date else None

    def _build_event(sentence: str, index: int) -> Optional[dict]:
        if not re.search(r'\b(schedule|set|callback|review|meeting|call|book|calendar|event|ticket)\b|बुक|कैलेंडर|इवेंट|टिकट', sentence, re.IGNORECASE):
            return None

        event_date = meeting_date
        lower = sentence.lower()
        if 'tomorrow' in lower or 'kal' in lower:
            event_date = meeting_date + timedelta(days=1)
        elif 'today' in lower or re.search(r'\baaj\b', lower):
            event_date = meeting_date

        hour = 11 if re.search(r'\b11\b', sentence) else 15 if re.search(r'\b3\s*(?:pm|baje)\b', lower) else 14
        if 'pm' in lower and hour < 12:
            hour += 12
        if 'shaam' in lower and hour < 12:
            hour += 12

        start_dt = event_date.replace(hour=hour, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(hours=1)
        event_title = 'Follow-up Call'
        if re.search(r'callback', sentence, re.IGNORECASE):
            event_title = 'Buyer Callback'
        elif re.search(r'review', sentence, re.IGNORECASE):
            event_title = 'Review Meeting'
        elif re.search(r'calendar|event|book|ticket|बुक|कैलेंडर|इवेंट|टिकट', sentence, re.IGNORECASE):
            event_title = 'Scheduled Follow-up'

        return {
            "id": f"CAL_{index:03d}",
            "title": event_title,
            "description": sentence[:180],
            "start_datetime": start_dt.isoformat(),
            "end_datetime": end_dt.isoformat(),
            "attendees": [],
            "source": "local fallback",
            "type": "MEETING",
        }

    tasks = []
    calendar_events = []
    for i, sentence in enumerate(task_sentences[:6], start=1):
        cleaned_sentence = re.sub(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*:\s*', '', sentence).strip()
        assignee = _extract_assignee(sentence)
        deadline_hint = _extract_deadline_hint(sentence)
        due_date = _resolve_relative_due_date(sentence)
        event = _build_event(sentence, len(calendar_events) + 1)
        if event:
            calendar_events.append(event)
        tasks.append({
            "id": f"TASK_{i:03d}",
            "title": cleaned_sentence[:120],
            "description": f"Deadline mentioned: {deadline_hint}" if deadline_hint else None,
            "assignee": assignee,
            "priority": "MEDIUM",
            "category": "OTHER",
            "status": "TODO",
            "due_date": due_date,
            "deadline_source": f"transcript: {deadline_hint}" if deadline_hint else "not specified",
            "dependencies": [],
            "context": "Extracted via local fallback (n8n unavailable)",
        })

    # Build a basic MOM from the first few sentences
    summary_sentences = sentences[:4]
    mom_points = "\n".join(f"- {s}" for s in summary_sentences) if summary_sentences else "No discussion points captured."
    action_items = "\n".join(f"{i}. {t['title']}" for i, t in enumerate(tasks, 1)) if tasks else "No action items identified."
    summary = ". ".join(summary_sentences[:2]) if summary_sentences else transcript[:200]

    mail_body = (
        f"# Minutes of Meeting: {title}\n"
        f"**Date:** {meeting_date.strftime('%B %d, %Y')}\n\n"
        f"---\n\n"
        f"## Discussion Points\n\n{mom_points}\n\n"
        f"---\n\n"
        f"## Action Items\n\n{action_items}"
    )

    raw_transcript = f"[Speaker 1]: {transcript}"
    return {
        "raw_transcript": raw_transcript,
        "transcript_en": raw_transcript,
        "transcript_hi": None,
        "transcript_hinglish": None,
        "attendees": [{
            "speaker_id": "SPEAKER_1",
            "name": "Speaker 1",
            "email": None,
            "identified": False,
            "hint": "Fallback mode — speaker diarization unavailable",
        }],
        "tasks": tasks,
        "calendar_events": calendar_events,
        "mail": {
            "subject": f"MoM: {title} - {meeting_date.strftime('%Y-%m-%d')}",
            "to": [],
            "cc": [],
            "body": mail_body,
            "sent": False,
            "sent_at": None,
        },
        "summary": summary,
        "tags": [],
        "sentiment": None,
        "confidence": None,
        "model_used": "local-fallback",
    }


def _speaker_map_to_transcript_text(speaker_map: dict) -> str:
    return "\n".join(
        f"{speaker}: {text}" for speaker, text in (speaker_map or {}).items() if str(text or "").strip()
    )


# Anything outside basic Latin-1 (e.g. Devanagari, Tamil, Telugu, Bengali, Han,
# Hangul, Hiragana, Arabic, etc.) means the transcript is not English.
_NON_LATIN_RE = re.compile(r"[^\x00-\x7F]")


def _looks_non_english(text: str) -> bool:
    if not text:
        return False
    sample = text[:2000]
    non_latin = len(_NON_LATIN_RE.findall(sample))
    # If more than ~3% of the first 2k chars are non-ASCII, treat as non-English
    return non_latin >= max(8, int(len(sample) * 0.03))


async def _translate_via_brd_agent(text: str, target_language: str = "English") -> Optional[str]:
    """Ask the brd-agent (which already holds the LLM gateway credentials) to
    translate the supplied transcript to English. Returns None on failure so
    the caller can leave the field empty rather than insert a placeholder.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        url = f"{config.BRD_AGENT_API_BASE.rstrip('/')}/translate"
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                url,
                json={
                    "text": text,
                    "target_language": target_language,
                    "preserve_speaker_tags": True,
                },
            )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            logger.warning(f"[Translate] brd-agent translate returned: {payload.get('error')}")
            return None
        translated = (payload.get("translated") or "").strip()
        return translated or None
    except Exception as exc:
        logger.warning(f"[Translate] brd-agent /translate failed: {exc}")
        return None


async def _ensure_english_translation(updates: dict) -> dict:
    """If transcript_en is empty/missing but raw_transcript looks non-English,
    call the translation API and populate transcript_en. Idempotent."""
    transcript_en = (updates.get("transcript_en") or "").strip()
    raw = (updates.get("raw_transcript") or "").strip()
    if not raw:
        return updates

    if transcript_en and not _looks_non_english(transcript_en):
        # Already have a usable English version
        return updates

    if not _looks_non_english(raw):
        # Source is already English-ish — mirror it so the UI has both tabs
        if not transcript_en:
            updates["transcript_en"] = raw
        return updates

    translated = await _translate_via_brd_agent(raw, target_language="English")
    if translated:
        updates["transcript_en"] = translated
        existing_warning = (updates.get("warning") or "").strip()
        note = "Transcript translated to English via LLM."
        updates["warning"] = f"{existing_warning} | {note}".strip(" |") if existing_warning else note
    return updates


def _enrich_sparse_meeting_updates(
    transcript: str,
    meeting_date: datetime,
    title: str,
    updates: dict,
    participants: Optional[List[str]] = None,
) -> dict:
    enriched = dict(updates or {})
    transcript_text = str(transcript or "").strip()
    if not transcript_text:
        return enriched

    existing_tasks = [item for item in (enriched.get("tasks") or []) if isinstance(item, dict)]
    existing_calendar = [item for item in (enriched.get("calendar_events") or []) if isinstance(item, dict)]
    existing_mail = enriched.get("mail") if isinstance(enriched.get("mail"), dict) else {}
    summary_text = str(enriched.get("summary") or "").strip()
    needs_summary = not summary_text or summary_text.lower() == "no summary available."
    needs_mail_body = not str(existing_mail.get("body") or "").strip()

    if existing_tasks and existing_calendar and not needs_summary and not needs_mail_body:
        return enriched

    local_signals = _fallback_process_transcript(
        transcript_text,
        meeting_date,
        title,
        participants=participants,
    )

    if not existing_tasks and local_signals.get("tasks"):
        enriched["tasks"] = local_signals["tasks"]
    if not existing_calendar and local_signals.get("calendar_events"):
        enriched["calendar_events"] = local_signals["calendar_events"]
    if needs_summary and local_signals.get("summary"):
        enriched["summary"] = local_signals["summary"]
    if needs_mail_body and local_signals.get("mail"):
        enriched["mail"] = {**local_signals.get("mail", {}), **existing_mail}
    elif existing_mail:
        enriched["mail"] = existing_mail
    if not enriched.get("attendees") and local_signals.get("attendees"):
        enriched["attendees"] = local_signals["attendees"]

    model_used = str(enriched.get("model_used") or "").strip()
    if "local-signal-enrichment" not in model_used:
        enriched["model_used"] = f"{model_used}+local-signal-enrichment".strip("+") if model_used else "local-signal-enrichment"

    return enriched


def _update_processing_state(
    meeting_id: str,
    *,
    progress: int,
    stage: str,
    message: str,
    status: str = ProcessingStatus.PROCESSING.value,
) -> None:
    store = get_store()
    store.update_meeting(meeting_id, {
        "status": status,
        "processing_progress": progress,
        "processing_stage": stage,
        "processing_message": message,
        "updated_at": datetime.utcnow().isoformat(),
    })


# The downstream n8n google_tool_event workflow uses a Groq node whose
# format_final_json_response schema only accepts these six task categories.
# Anything else fails validation, the workflow errors out, and the email +
# calendar dispatch silently produces malformed events. We coerce every
# outgoing category into this set so the workflow never sees an unexpected
# value.
ALLOWED_TASK_CATEGORIES = {"Development", "Research", "Infra", "Bug", "Ops", "Documentation"}

_CATEGORY_ALIASES = {
    "DEV": "Development", "ENGINEERING": "Development", "ENG": "Development",
    "BUILD": "Development", "FEATURE": "Development", "IMPLEMENTATION": "Development",
    "RESEARCH": "Research", "ANALYSIS": "Research", "DISCOVERY": "Research",
    "STUDY": "Research", "INVESTIGATE": "Research",
    "INFRA": "Infra", "INFRASTRUCTURE": "Infra", "DEVOPS": "Infra",
    "DEPLOY": "Infra", "PLATFORM": "Infra",
    "BUG": "Bug", "DEFECT": "Bug", "FIX": "Bug", "REGRESSION": "Bug",
    "OPS": "Ops", "OPERATIONS": "Ops", "OPERATIONAL": "Ops", "OTHER": "Ops",
    "MISC": "Ops", "GENERAL": "Ops", "ADMIN": "Ops", "PROCESS": "Ops",
    "MEETING": "Ops", "FOLLOWUP": "Ops", "FOLLOW-UP": "Ops",
    "DOCUMENTATION": "Documentation", "DOCS": "Documentation",
    "WRITE": "Documentation", "BRD": "Documentation", "SPEC": "Documentation",
    "DOCUMENT": "Documentation",
}


def _coerce_task_category(raw_value) -> str:
    if not raw_value:
        return "Ops"
    text = str(raw_value).strip()
    if not text:
        return "Ops"
    titled = text.title()
    if titled in ALLOWED_TASK_CATEGORIES:
        return titled
    key = re.sub(r"[^A-Z]+", "", text.upper())
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    upper = text.upper()
    for alias, allowed in _CATEGORY_ALIASES.items():
        if alias in upper:
            return allowed
    return "Ops"


_ALLOWED_PRIORITIES = {"High", "Medium", "Low"}


def _coerce_task_priority(raw_value) -> str:
    if not raw_value:
        return "Medium"
    text = str(raw_value).strip().title()
    if text in _ALLOWED_PRIORITIES:
        return text
    upper = text.upper()
    if "URGENT" in upper or "CRITICAL" in upper or "P0" in upper or "P1" in upper:
        return "High"
    if "LOW" in upper or "P3" in upper or "P4" in upper:
        return "Low"
    return "Medium"


def _format_task_for_google_tools(task: dict, meeting_date: Optional[str]) -> dict:
    due_date = task.get("due_date")
    start_date = None

    if meeting_date:
        try:
            start_date = datetime.fromisoformat(str(meeting_date)).date().isoformat()
        except ValueError:
            start_date = None

    return {
        "task_title": task.get("title") or task.get("task_title") or "Untitled task",
        "description": task.get("description") or "",
        # Always one of the six allowed enums — see ALLOWED_TASK_CATEGORIES
        "category": _coerce_task_category(task.get("category")),
        "priority": _coerce_task_priority(task.get("priority")),
        "start_date": start_date,
        "edd": str(due_date) if due_date else None,
        "calendar_block": bool(due_date),
    }


def _format_event_for_google_tools(event: dict, recipients: List[str]) -> Optional[dict]:
    """Build a payload rich enough that the n8n google_tool_event workflow
    cannot silently drop fields when forwarding to the Google Calendar API.

    Returns None for events that lack a usable title — those would otherwise
    create the empty-title "," calendar invites that have been observed.
    """
    if not isinstance(event, dict):
        return None

    title = str(event.get("title") or event.get("event_title") or "").strip()
    if not title:
        return None

    start_dt = event.get("start_datetime") or event.get("start") or event.get("startDateTime")
    end_dt = event.get("end_datetime") or event.get("end") or event.get("endDateTime")

    event_date = None
    event_time = None
    if start_dt:
        try:
            parsed = datetime.fromisoformat(str(start_dt).replace("Z", "+00:00"))
            event_date = parsed.date().isoformat()
            event_time = parsed.strftime("%H:%M")
        except (ValueError, TypeError):
            event_date = None
            event_time = None

    description = event.get("description") or event.get("notes") or ""
    if not description and event_date:
        description = f"Scheduled follow-up — {title}"

    participants = []
    for attendee in event.get("attendees") or []:
        if isinstance(attendee, str) and attendee.strip():
            participants.append(attendee.strip())
        elif isinstance(attendee, dict):
            email = (attendee.get("email") or "").strip()
            if email:
                participants.append(email)
    if not participants and recipients:
        participants = list(recipients)

    return {
        "event_title": title,
        "title": title,
        "event_date": event_date or "",
        "event_time": event_time or "",
        "start_datetime": str(start_dt) if start_dt else "",
        "end_datetime": str(end_dt) if end_dt else "",
        "description": description,
        "notes": description,
        "participants": participants,
        "attendees": participants,
        "event_type": str(event.get("type") or "MEETING"),
        # legacy shape kept for backwards compat with older workflow versions
        "time": event_time or description,
    }


def _parse_summary_object(summary: Optional[object]) -> Optional[dict]:
    if not summary:
        return None

    if isinstance(summary, dict):
        return summary

    text = str(summary).strip()
    if not text.startswith("{"):
        return None

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(text)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, SyntaxError):
            return None


def _build_professional_mom_body(meeting: dict, recipients: List[str]) -> str:
    """Produce a launch-mail-style MoM email body server-side so the
    recipient always gets a full, professional brief — not the terse 2-line
    summary AISummarization sometimes returns. Mirrors the frontend
    `buildMomBody` so the auto-dispatched email matches what the user sees.
    """
    date_str = ""
    try:
        when = meeting.get("created_at") or meeting.get("date") or datetime.utcnow().isoformat()
        date_str = datetime.fromisoformat(str(when)).strftime("%B %d, %Y")
    except Exception:
        date_str = datetime.utcnow().strftime("%B %d, %Y")

    title = (meeting.get("title") or "Meeting").strip()
    tasks = [t for t in (meeting.get("tasks") or []) if isinstance(t, dict)]
    events = [e for e in (meeting.get("calendar_events") or []) if isinstance(e, dict)]
    attendees = [a for a in (meeting.get("attendees") or []) if isinstance(a, dict)]
    kpis = meeting.get("kpis") or {}
    automation = meeting.get("automation") or {}
    parsed_summary = _parse_summary_object(meeting.get("summary")) or {}

    attendee_lines = []
    for a in attendees:
        name = (a.get("name") or a.get("speaker_id") or "").strip()
        email = (a.get("email") or "").strip()
        if email and name:
            attendee_lines.append(f"- **{name}** ({email})")
        elif name:
            attendee_lines.append(f"- **{name}**")
        elif email:
            attendee_lines.append(f"- {email}")
    attendee_block = "\n".join(attendee_lines) if attendee_lines else "- _(none captured)_"

    recipient_line = f"**To:** {', '.join(recipients)}" if recipients else ""
    topic = parsed_summary.get("topic") or ""
    topic_line = f"**Topic:** {topic}\n\n" if topic else ""
    discussion = (
        parsed_summary.get("discussion_summary")
        or parsed_summary.get("summary")
        or meeting.get("summary")
        or "_Meeting recap pending review._"
    )
    if isinstance(discussion, dict):
        discussion = json.dumps(discussion)
    discussion = str(discussion).strip()
    decision_block = f"\n\n## Decisions\n{parsed_summary.get('decisions')}" if parsed_summary.get("decisions") else ""

    if tasks:
        task_rows = [
            "| # | Action Item | Owner | Category | Priority | Due |",
            "|---|---|---|---|---|---|",
        ]
        for i, t in enumerate(tasks, start=1):
            task_rows.append(
                f"| {i} | **{(t.get('title') or 'Untitled').strip()}** "
                f"| {t.get('assignee') or '_TBD_'} "
                f"| {t.get('category') or 'OPS'} "
                f"| {t.get('priority') or 'MEDIUM'} "
                f"| {t.get('due_date') or '_TBD_'} |"
            )
        tasks_table = "\n".join(task_rows)
    else:
        tasks_table = "_No action items captured._"

    if events:
        cal_lines = []
        for i, e in enumerate(events, start=1):
            start = e.get("start_datetime") or ""
            start_pretty = start
            try:
                start_pretty = datetime.fromisoformat(str(start)).strftime("%b %d, %Y at %I:%M %p")
            except Exception:
                start_pretty = start or "_TBD_"
            cal_lines.append(
                f"{i}. **{(e.get('title') or 'Follow-up').strip()}** — {start_pretty}\n"
                f"   {e.get('description') or ''}".rstrip()
            )
        calendar_block = "\n\n".join(cal_lines)
    else:
        calendar_block = "_No calendar holds scheduled._"

    kpi_lines = []
    if kpis:
        kpi_lines = [
            f"- **Execution Health Index:** {round(float(kpis.get('execution_health_index') or 0))} / 100",
            f"- **Context Completeness:** {round(float(kpis.get('context_completeness_score') or 0))}%",
            f"- **Action Leakage:** {round(float(kpis.get('action_leakage_rate') or 0))}%",
            f"- **Ownership Coverage:** {round(float(kpis.get('ownership_coverage') or 0))}%",
            f"- **Auto-dispatch:** "
            + ("Email + Calendar sent automatically" if automation.get("dispatch_success") else "Pending"),
        ]
    kpi_block = "\n".join(kpi_lines) if kpi_lines else "_KPIs pending._"

    return (
        f"# Minutes of Meeting — {title}\n\n"
        f"**Date:** {date_str}\n"
        f"{recipient_line}\n"
        f"{topic_line}---\n\n"
        f"## Attendees\n{attendee_block}\n\n---\n\n"
        f"## Discussion\n{discussion}{decision_block}\n\n---\n\n"
        f"## Action Items\n{tasks_table}\n\n---\n\n"
        f"## Calendar Holds\n{calendar_block}\n\n---\n\n"
        f"## Execution Snapshot\n{kpi_block}\n\n---\n\n"
        f"## Next Steps\n"
        f"1. Confirm action item owners and deadlines by replying to this email.\n"
        f"2. Calendar holds above will be sent as Google Calendar invites — accept or reschedule.\n"
        f"3. If a BRD is needed for this initiative, click **Generate BRD** in the workspace — it pulls this conversation context into a structured BRD draft in RequireWise.\n\n"
        f"---\n\n"
        f"_Auto-generated by Canopy Meeting Workspace._\n"
    )


def _build_professional_mom_subject(meeting: dict) -> str:
    """Sensible subject: "MoM • <Title> • <Date>". Avoids the generic
    'AI daily scrum summary' template that AISummarization sometimes emits."""
    title = (meeting.get("title") or "").strip() or "Meeting follow-up"
    try:
        when = meeting.get("created_at") or meeting.get("date") or datetime.utcnow().isoformat()
        date_str = datetime.fromisoformat(str(when)).strftime("%d %b %Y")
    except Exception:
        date_str = datetime.utcnow().strftime("%d %b %Y")
    return f"MoM • {title[:80]} • {date_str}"


def _format_mom_for_google_tools(
    meeting: dict,
    fallback_body: Optional[str] = None,
    fallback_owner: Optional[str] = None
) -> List[dict]:
    parsed_summary = _parse_summary_object(meeting.get("summary"))
    if parsed_summary:
        return [{
            "topic": parsed_summary.get("topic") or meeting.get("title") or "Meeting Summary",
            "discussion_summary": parsed_summary.get("discussion_summary") or parsed_summary.get("summary") or "",
            "decisions": parsed_summary.get("decisions") or parsed_summary.get("next_steps") or "",
            "owner": parsed_summary.get("owner") or parsed_summary.get("owners") or fallback_owner or "",
        }]

    body_text = (fallback_body or (meeting.get("mail") or {}).get("body") or meeting.get("summary") or "").strip()
    return [{
        "topic": meeting.get("title") or "Meeting Summary",
        "discussion_summary": body_text,
        "decisions": "",
        "owner": fallback_owner or "",
    }]


def _build_google_tools_payload(
    meeting: dict,
    recipients: List[str],
    fallback_body: Optional[str] = None,
    fallback_owner: Optional[str] = None
) -> dict:
    meeting_date = meeting.get("date")

    # Drop empty-title events — those produce the blank-comma calendar
    # invites users see otherwise. And send the rich shape with
    # start_datetime + event_date + event_time + participants so the n8n
    # google_tool_event workflow can't lose fields downstream.
    calendar_items = []
    for event in meeting.get("calendar_events", []) or []:
        formatted = _format_event_for_google_tools(event, recipients)
        if formatted:
            calendar_items.append(formatted)

    task_items = [
        _format_task_for_google_tools(task, meeting_date)
        for task in meeting.get("tasks", []) or []
        if isinstance(task, dict)
    ]

    return {
        "recipients": recipients,
        "calender": calendar_items,
        "Task": task_items,
        "MOM": _format_mom_for_google_tools(meeting, fallback_body=fallback_body, fallback_owner=fallback_owner),
    }


def _slugify_meeting_title(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or f"meeting-brief-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"


def _build_brd_generation_prompt(meeting: dict) -> str:
    attendees = [
        ", ".join(
            filter(None, [attendee.get("name"), attendee.get("email")])
        )
        for attendee in (meeting.get("attendees") or [])
        if isinstance(attendee, dict)
    ]
    tasks = [task for task in (meeting.get("tasks") or []) if isinstance(task, dict)]
    calendar_events = [event for event in (meeting.get("calendar_events") or []) if isinstance(event, dict)]
    kpis = meeting.get("kpis") or {}
    mail = meeting.get("mail") or {}
    automation = meeting.get("automation") or {}

    task_lines = "\n".join(
        f"- {task.get('title') or 'Untitled task'} | owner: {task.get('assignee') or 'Unassigned'} | due: {task.get('due_date') or 'Not set'} | priority: {task.get('priority') or 'Not set'} | context: {task.get('description') or task.get('context') or 'n/a'}"
        for task in tasks
    ) or "- No explicit action items extracted"

    calendar_lines = "\n".join(
        f"- {event.get('title') or 'Untitled event'} | start: {event.get('start_datetime') or 'n/a'} | end: {event.get('end_datetime') or 'n/a'}"
        for event in calendar_events
    ) or "- No calendar events extracted"

    attendee_lines = "\n".join(f"- {entry}" for entry in attendees if entry) or "- No attendees captured"
    transcript = meeting.get("transcript_en") or meeting.get("raw_transcript") or ""
    summary = meeting.get("summary") or "No summary captured"
    email_body = mail.get("body") or "No email body captured"
    missing_fields = ", ".join(kpis.get("missing_fields") or []) or "none"

    return f"""You are generating a context-rich Business Requirements Document from a real meeting record.

Use only the grounded facts below. If something is not clearly stated, label it as an assumption or open question instead of inventing it.

Meeting title: {meeting.get('title') or 'Untitled meeting'}
Meeting date: {meeting.get('date') or 'Unknown'}

Attendees:
{attendee_lines}

Executive summary:
{summary}

Transcript:
{transcript}

Action items:
{task_lines}

Calendar and follow-up events:
{calendar_lines}

Follow-up email draft:
{email_body}

Execution intelligence:
- Execution Health Index: {kpis.get('execution_health_index', 'n/a')}
- Context Completeness Score: {kpis.get('context_completeness_score', 'n/a')}
- Action Leakage Rate: {kpis.get('action_leakage_rate', 'n/a')}
- Ownership Coverage: {kpis.get('ownership_coverage', 'n/a')}
- Automation Success: {automation.get('dispatch_success', False)}
- Missing Fields: {missing_fields}

Create a strong BRD in markdown with these sections:
1. Executive Summary
2. Business Problem
3. Objectives and Success Metrics
4. Stakeholders and Users
5. Functional Requirements
6. Non-Functional Requirements
7. Process Flow or Operational Workflow
8. Risks, Dependencies, and Open Questions
9. Delivery Priorities and Next Steps

Where possible, turn meeting actions and constraints into formal requirements. Include a small section for assumptions clearly marked as assumptions."""


class GenerateMeetingBRDRequest(BaseModel):
    filename: Optional[str] = None


def _unique_recipients(values: List[Optional[str]]) -> List[str]:
    recipients: List[str] = []
    seen = set()
    for value in values:
        email = str(value or "").strip()
        if not email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        recipients.append(email)
    return recipients


def _coerce_text_request_attendees(request: MeetingTextProcessRequest) -> List[dict]:
    names = [name.strip() for name in (request.participants or []) if str(name).strip()]
    emails = [str(email).strip() for email in (request.attendee_emails or []) if str(email).strip()]
    length = max(len(names), len(emails))
    attendees = []
    for index in range(length):
        attendees.append({
            "speaker_id": f"SPEAKER_{index + 1}",
            "name": names[index] if index < len(names) else None,
            "email": emails[index] if index < len(emails) else None,
            "identified": bool((index < len(names) and names[index]) or (index < len(emails) and emails[index])),
            "hint": "Provided from transcript form",
        })
    return attendees


def _build_text_speaker_map(transcript: str, participants: Optional[List[str]] = None) -> dict:
    speaker_map = {}
    current_speaker = None
    current_lines: List[str] = []
    label_pattern = re.compile(r'^\[?([A-Z][a-z]+(?: [A-Z][a-z]+)?)\]?\s*:\s*(.*)$')

    def _flush() -> None:
        nonlocal current_speaker, current_lines
        if current_speaker and current_lines:
            content = " ".join(part for part in current_lines if part).strip()
            if content:
                speaker_map[current_speaker] = (
                    f"{speaker_map[current_speaker]} {content}".strip()
                    if current_speaker in speaker_map
                    else content
                )
        current_speaker = None
        current_lines = []

    for raw_line in str(transcript or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = label_pattern.match(line)
        if match:
            _flush()
            current_speaker = match.group(1).strip()
            body = match.group(2).strip()
            current_lines = [body] if body else []
            continue

        if current_speaker:
            current_lines.append(line)
            continue

        current_speaker = "Speaker 1"
        current_lines = [line]

    _flush()

    if speaker_map:
        return speaker_map

    participant_names = [name.strip() for name in (participants or []) if str(name or "").strip()]
    if len(participant_names) == 1:
        return {participant_names[0]: str(transcript or "").strip()}

    return {"Speaker 1": str(transcript or "").strip()}


def _merge_attendees(base_attendees: Optional[List[dict]], generated_attendees: Optional[List[dict]]) -> List[dict]:
    base = [attendee for attendee in (base_attendees or []) if isinstance(attendee, dict)]
    generated = [attendee for attendee in (generated_attendees or []) if isinstance(attendee, dict)]

    if not base:
        return generated
    if not generated:
        return base

    # Separate base attendees by whether they carry a usable email. Email-bearing
    # entries (from the upload form's attendee_emails) MUST survive the merge so
    # auto-dispatch has a recipient.
    base_email_only = []  # email + maybe identified, no name
    base_with_name = []
    for attendee in base:
        email = str(attendee.get("email") or "").strip()
        name = str(attendee.get("name") or "").strip()
        if email and not name:
            base_email_only.append(attendee)
        else:
            base_with_name.append(attendee)

    merged: List[dict] = []
    used_named_indexes = set()

    for index, inferred in enumerate(generated):
        original = {}
        inferred_name = str(inferred.get("name") or "").strip()
        if inferred_name:
            for base_index, candidate in enumerate(base_with_name):
                if base_index in used_named_indexes:
                    continue
                candidate_name = str(candidate.get("name") or "").strip()
                if candidate_name and candidate_name.lower() == inferred_name.lower():
                    original = candidate
                    used_named_indexes.add(base_index)
                    break
        if not original and index < len(base_with_name) and index not in used_named_indexes:
            original = base_with_name[index]
            used_named_indexes.add(index)
        if original.get("name") and re.fullmatch(r"Speaker\s*\d+", inferred_name, re.IGNORECASE):
            inferred = {**inferred, "name": original.get("name")}
        combined = {**original, **inferred}

        for key in ["name", "email", "hint"]:
            if not combined.get(key) and original.get(key):
                combined[key] = original.get(key)

        if original.get("identified") and not combined.get("identified"):
            combined["identified"] = True

        combined.setdefault("speaker_id", original.get("speaker_id") or inferred.get("speaker_id") or f"SPEAKER_{index + 1}")
        merged.append(combined)

    for index, original in enumerate(base_with_name):
        if index not in used_named_indexes:
            merged.append(original)

    # Always preserve email-only recipients at the END so they show up as
    # dispatchable attendees regardless of webhook-detected speakers.
    merged.extend(base_email_only)

    return merged


def _backfill_task_assignees(meeting: dict) -> List[dict]:
    tasks = [dict(task) for task in (meeting.get("tasks") or []) if isinstance(task, dict)]
    if not tasks:
        return tasks

    attendees = [attendee for attendee in (meeting.get("attendees") or []) if isinstance(attendee, dict)]
    attendee_names = [str(attendee.get("name") or "").strip() for attendee in attendees if str(attendee.get("name") or "").strip()]
    transcript = "\n".join(
        value for value in [
            str(meeting.get("raw_transcript") or ""),
            str(meeting.get("transcript_en") or ""),
            str((meeting.get("mail") or {}).get("body") or ""),
        ]
        if value
    )
    sentences = [segment.strip() for segment in re.split(r'(?<=[.!?])\s+|\n+', transcript) if segment.strip()]
    stop_words = {
        "the", "and", "with", "from", "that", "this", "will", "should", "would", "could", "please",
        "into", "also", "have", "has", "because", "about", "their", "there", "need", "needs", "for",
        "our", "your", "client", "someone", "team", "great", "old", "include",
    }

    def _tokenize(value: str) -> set:
        return {
            token for token in re.findall(r"[a-zA-Z]{3,}", str(value or "").lower())
            if token not in stop_words
        }

    def _names_in_sentence(sentence: str) -> List[str]:
        found = []
        for name in attendee_names:
            if re.search(rf'\b{re.escape(name)}\b', sentence, re.IGNORECASE):
                found.append(name)
        speaker = re.match(r'^\[?([A-Z][a-z]+(?: [A-Z][a-z]+)?)\]?\s*:', sentence)
        if speaker and speaker.group(1) in attendee_names and speaker.group(1) not in found:
            found.append(speaker.group(1))
        return found

    def _has_commitment_cue(sentence: str) -> bool:
        return bool(re.search(
            r"\b(i|i'll|i will|main|mai|karti hoon|kar dunga|kar dungi|bhej dungi|"
            r"bhej dunga|set kar|schedule|update|send|review|approve|add)\b",
            sentence,
            re.IGNORECASE,
        ))

    updated_tasks = []
    for task in tasks:
        task_text = " ".join([
            str(task.get("title") or ""),
            str(task.get("description") or ""),
            str(task.get("context") or ""),
        ])

        if str(task.get("assignee") or "").strip():
            if re.search(r'\b(someone|koi|team)\b', task_text, re.IGNORECASE):
                task["assignee"] = None
            updated_tasks.append(task)
            continue

        if re.search(r'\b(someone|koi|team)\b', task_text, re.IGNORECASE):
            updated_tasks.append(task)
            continue

        task_keywords = _tokenize(task_text)
        best_name = None
        best_score = 0

        for sentence in sentences:
            if re.search(r'\b(someone|koi|team)\b', sentence, re.IGNORECASE):
                continue
            candidates = _names_in_sentence(sentence)
            if not candidates:
                continue
            score = len(task_keywords & _tokenize(sentence))
            if score == 1 and _has_commitment_cue(sentence) and len(candidates) == 1:
                score = 2
            if score > best_score and score >= 2:
                best_score = score
                best_name = candidates[0]

        if best_name:
            task["assignee"] = best_name
        updated_tasks.append(task)

    return updated_tasks


def _collect_dispatch_recipients(meeting: dict, stored_user: Optional[dict]) -> List[str]:
    settings = (stored_user or {}).get("settings") or {}
    attendee_emails = [attendee.get("email") for attendee in (meeting.get("attendees") or []) if isinstance(attendee, dict)]
    mail_to = meeting.get("mail", {}).get("to", []) if isinstance(meeting.get("mail"), dict) else []
    user_candidates = [
        (stored_user or {}).get("email"),
        settings.get("profile_email"),
    ]
    return _unique_recipients(attendee_emails + list(mail_to) + user_candidates)


def _refresh_meeting_metrics(meeting: dict, store=None) -> Optional[dict]:
    if not meeting or not meeting.get("meeting_id"):
        return meeting
    store = store or get_store()
    refresh_updates = {}
    enriched_tasks = _backfill_task_assignees(meeting)
    if enriched_tasks != (meeting.get("tasks") or []):
        refresh_updates["tasks"] = enriched_tasks
        meeting = {**meeting, "tasks": enriched_tasks}
    refresh_updates["kpis"] = compute_meeting_kpis(meeting)
    updated = store.update_meeting(meeting["meeting_id"], refresh_updates)
    return updated


async def _ensure_english_mail_body(meeting: dict, store) -> dict:
    """Ensure meeting.mail.body is in English before we hand it off to the
    email/google_tool_event dispatcher. When AISummarization runs cleanly,
    it already produces English output. But the deterministic regex fallback
    builds the MoM from raw transcript sentences — so for a Hindi audio
    meeting the body would otherwise be sent in Hindi. Translate it once
    and persist, so downstream callers see English.
    """
    mail = meeting.get("mail") or {}
    body = (mail.get("body") or "").strip()
    if not body:
        return meeting
    if not _looks_non_english(body):
        return meeting

    translated = await _translate_via_brd_agent(body, target_language="English")
    if not translated:
        return meeting

    new_mail = dict(mail)
    new_mail["body"] = translated
    new_mail.setdefault("body_native", body)
    store.update_meeting(meeting["meeting_id"], {"mail": new_mail})
    refreshed = store.get_meeting(meeting["meeting_id"])
    return refreshed or meeting


async def _auto_dispatch_meeting_outputs(meeting_id: str, stored_user: Optional[dict], store=None) -> Optional[dict]:
    store = store or get_store()
    meeting = store.get_meeting(meeting_id)
    if not meeting:
        return None

    # Always send English MoM out — even when the transcript was Hindi
    meeting = await _ensure_english_mail_body(meeting, store)

    recipients = _collect_dispatch_recipients(meeting, stored_user)

    # Overwrite the mail body with the professional, launch-style MoM so
    # whatever lands in recipients' inboxes has full context (attendees,
    # action items table, calendar holds, KPIs, next steps) — not just the
    # terse AISummarization output. Subject normalized to "MoM • Title • Date".
    professional_body = _build_professional_mom_body(meeting, recipients)
    professional_subject = _build_professional_mom_subject(meeting)
    mail_data = dict(meeting.get("mail") or {})
    mail_data["subject"] = professional_subject
    mail_data["body_native"] = mail_data.get("body")  # preserve original
    mail_data["body"] = professional_body
    store.update_meeting(meeting_id, {"mail": mail_data})
    meeting = store.get_meeting(meeting_id)

    baseline_timestamp = meeting.get("processed_at") or meeting.get("created_at") or datetime.utcnow().isoformat()
    automation = dict(meeting.get("automation") or {})
    automation.update({
        "baseline_timestamp": baseline_timestamp,
        "recipients": recipients,
        "source": automation.get("source") or "meeting-master-auto-dispatch",
    })

    if not recipients:
        automation.update({
            "dispatch_success": False,
            "auto_sent_email": False,
            "auto_scheduled_calendar": False,
            "error": "No recipient emails available for auto-dispatch",
        })
        updated = store.update_meeting(meeting_id, {"automation": automation})
        return _refresh_meeting_metrics(updated, store=store)

    payload = _build_google_tools_payload(
        meeting,
        recipients=recipients,
        fallback_body=(meeting.get("mail") or {}).get("body") if isinstance(meeting.get("mail"), dict) else None,
        fallback_owner=(stored_user or {}).get("name"),
    )
    result = await trigger_google_tools_webhook(
        recipients=payload["recipients"],
        calendar=payload["calender"],
        tasks=payload["Task"],
        mom=payload["MOM"],
    )

    dispatched_at = datetime.utcnow().isoformat()
    automation.update({
        "dispatch_success": bool(result.get("success")),
        "auto_sent_email": bool(result.get("success")),
        "auto_scheduled_calendar": bool(result.get("success") and payload["calender"]),
        "dispatched_at": dispatched_at if result.get("success") else None,
        "error": None if result.get("success") else result.get("message") or result.get("error") or "Dispatch failed",
    })

    updates = {"automation": automation}
    if result.get("success"):
        mail_data = dict(meeting.get("mail") or {})
        mail_data.update({
            "to": recipients,
            "sent": True,
            "sent_at": dispatched_at,
        })
        updates["mail"] = mail_data

    updated = store.update_meeting(meeting_id, updates)
    return _refresh_meeting_metrics(updated, store=store)

# NOTE: require_auth and get_current_user are imported from auth.py module.
# require_auth validates via Descope (auth-service) with guest JWT fallback.
# Usage: user: dict = Depends(require_auth)
# User dict has: id, user_id (alias), email, name, tier, is_guest, raw


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint — follows health_endpoint.instructions.md standard.
    Returns: status='ok', started (IST), host (SERVER_HOST env), version.
    """
    return HealthResponse(
        status="ok",
        started=STARTED_AT,
        host=os.environ.get("SERVER_HOST", "unknown"),
        version=config.API_VERSION,
    )


# =============================================================================
# Debug Endpoints (Enabled when DEBUG_MODE=true)
# =============================================================================

@app.get("/api/v1/debug/config", tags=["Debug"])
async def debug_config():
    """Debug endpoint: Show current configuration (DEBUG_MODE only)"""
    if not config.DEBUG_MODE:
        raise HTTPException(status_code=403, detail="Debug mode disabled")
    
    # Get env vars safely (hide actual keys)
    def mask_key(key: str) -> str:
        if not key or key == "CONFIGURE_ME" or len(key) < 10:
            return f"NOT_SET ({len(key) if key else 0} chars)"
        return f"SET ({key[:8]}...{key[-4:]}, {len(key)} chars)"
    
    return {
        "debug_mode": config.DEBUG_MODE,
        "auth_disabled": config.AUTH_DISABLED,
        "log_level": config.LOG_LEVEL,
        "keys": {
            "openrouter": mask_key(os.getenv("OPENROUTER_API_KEY", "")),
            "deepgram": mask_key(os.getenv("DEEPGRAM_API_KEY", "")),
            "groq": mask_key(os.getenv("GROQ_API_KEY", "")),
            "sarvam": mask_key(os.getenv("SARVAM_API_KEY", "")),
            "google_oauth": mask_key(os.getenv("GOOGLE_CLIENT_ID", "")),
        },
        "storage": {
            "backend": "json_file",
            "storage_file": config.STORAGE_FILE_PATH,
        },
        "stt_config": {
            "default_provider": os.getenv("DEFAULT_STT_PROVIDER", "sarvam"),
            "sarvam_available": bool(os.getenv("SARVAM_API_KEY")) and len(os.getenv("SARVAM_API_KEY", "")) > 10,
            "groq_available": bool(os.getenv("GROQ_API_KEY")) and len(os.getenv("GROQ_API_KEY", "")) > 10,
            "deepgram_available": bool(os.getenv("DEEPGRAM_API_KEY")) and len(os.getenv("DEEPGRAM_API_KEY", "")) > 10,
            "requires_real_provider": True,
        },
        "transcription_available": {
            "sarvam": bool(os.getenv("SARVAM_API_KEY")) and len(os.getenv("SARVAM_API_KEY", "")) > 10,
            "deepgram": bool(os.getenv("DEEPGRAM_API_KEY")) and len(os.getenv("DEEPGRAM_API_KEY", "")) > 10,
            "groq_whisper": bool(os.getenv("GROQ_API_KEY")) and len(os.getenv("GROQ_API_KEY", "")) > 10,
            "requires_real_provider": True
        },
        "llm_available": {
            "openrouter": bool(os.getenv("OPENROUTER_API_KEY")) and len(os.getenv("OPENROUTER_API_KEY", "")) > 10,
        }
    }


@app.get("/api/v1/debug/test", tags=["Debug"])
async def debug_test(feature: str = "all"):
    """Debug endpoint: Test specific features
    
    Params:
    - feature=all: Test all features
    - feature=transcription: Test audio transcription
    - feature=llm: Test LLM processing  
    - feature=storage: Test local storage access
    """
    if not config.DEBUG_MODE:
        raise HTTPException(status_code=403, detail="Debug mode disabled")
    
    results = {}
    
    if feature in ["all", "storage"]:
        try:
            store = get_store()
            results["storage"] = store.health()
        except Exception as e:
            results["storage"] = {"status": "ERROR", "error": str(e)}
    
    if feature in ["all", "llm"]:
        try:
            import httpx
            api_key = os.getenv("OPENROUTER_API_KEY", "")
            if api_key and len(api_key) > 10:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": "google/gemma-3-4b-it:free",
                            "messages": [{"role": "user", "content": "Say OK"}],
                            "max_tokens": 10
                        },
                        timeout=30.0
                    )
                    if resp.status_code == 200:
                        results["llm"] = {"status": "OK", "response": resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")}
                    else:
                        results["llm"] = {"status": "ERROR", "code": resp.status_code, "error": resp.text[:200]}
            else:
                results["llm"] = {"status": "NOT_CONFIGURED", "error": "OPENROUTER_API_KEY not set"}
        except Exception as e:
            results["llm"] = {"status": "ERROR", "error": str(e)}
    
    if feature in ["all", "transcription"]:
        sarvam_key = os.getenv("SARVAM_API_KEY", "")
        groq_key = os.getenv("GROQ_API_KEY", "")
        deepgram_key = os.getenv("DEEPGRAM_API_KEY", "")
        default_provider = os.getenv("DEFAULT_STT_PROVIDER", "sarvam")
        
        if sarvam_key and len(sarvam_key) > 10:
            results["transcription"] = {"status": "SARVAM_CONFIGURED", "provider": "sarvam", "default": default_provider}
        elif groq_key and len(groq_key) > 10:
            results["transcription"] = {"status": "GROQ_CONFIGURED", "provider": "groq_whisper", "default": default_provider}
        elif deepgram_key and len(deepgram_key) > 10:
            results["transcription"] = {"status": "DEEPGRAM_CONFIGURED", "provider": "deepgram", "default": default_provider}
        else:
            results["transcription"] = {
                "status": "NOT_CONFIGURED", 
                "provider": None,
                "note": "Set SARVAM_API_KEY (free, best for Hindi) or GROQ_API_KEY (free, multilingual) for real transcription. Audio processing will fail until one is configured."
            }
    
    return {
        "debug_mode": True,
        "feature_tested": feature,
        "results": results
    }


@app.get("/api/v1/debug/llm", tags=["Debug"])
async def debug_llm(
    prompt: str = "Say hello in one word",
    model: str = "google/gemma-3-4b-it:free",
    api_key: str = None,
    max_tokens: int = 50
):
    """Debug endpoint: Test LLM directly with params
    
    Params:
    - prompt: Text prompt to send to LLM
    - model: OpenRouter model name (default: google/gemma-3-4b-it:free)
    - api_key: Override API key (optional, uses server default)
    - max_tokens: Max response tokens
    
    Example: /api/v1/debug/llm?prompt=Translate%20hello%20to%20Hindi&model=google/gemma-3-12b-it:free
    """
    if not config.DEBUG_MODE:
        raise HTTPException(status_code=403, detail="Debug mode disabled")
    
    import httpx
    import time
    
    key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key or len(key) < 10:
        return {"status": "ERROR", "error": "No API key provided or configured"}
    
    start = time.time()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens
                },
                timeout=60.0
            )
            elapsed = time.time() - start
            
            if resp.status_code == 200:
                content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                return {
                    "status": "OK",
                    "model": model,
                    "prompt": prompt,
                    "response": content,
                    "response_time_ms": int(elapsed * 1000),
                    "usage": resp.json().get("usage", {})
                }
            else:
                return {
                    "status": "ERROR",
                    "model": model,
                    "http_code": resp.status_code,
                    "error": resp.text[:500],
                    "response_time_ms": int(elapsed * 1000)
                }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


@app.get("/api/v1/debug/translate", tags=["Debug"])
async def debug_translate(
    text: str = "Hello, how are you?",
    lang: str = "hi",
    model: str = "google/gemma-3-4b-it:free",
    api_key: str = None
):
    """Debug endpoint: Test translation via LLM
    
    Params:
    - text: Text to translate
    - lang: Target language code (hi=Hindi, ta=Tamil, te=Telugu, etc.)
    - model: OpenRouter model to use
    - api_key: Override API key (optional)
    
    Example: /api/v1/debug/translate?text=Meeting%20tomorrow&lang=hi
    """
    if not config.DEBUG_MODE:
        raise HTTPException(status_code=403, detail="Debug mode disabled")
    
    import httpx
    import time
    
    LANG_NAMES = {
        "hi": "Hindi", "ta": "Tamil", "te": "Telugu", "bn": "Bengali",
        "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam",
        "pa": "Punjabi", "or": "Odia", "as": "Assamese", "ur": "Urdu",
        "es": "Spanish", "fr": "French", "de": "German", "zh": "Chinese",
        "ja": "Japanese", "ko": "Korean", "ar": "Arabic", "ru": "Russian"
    }
    
    lang_name = LANG_NAMES.get(lang, lang)
    prompt = f"Translate the following text to {lang_name}. Return ONLY the translation, nothing else:\n\n{text}"
    
    key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key or len(key) < 10:
        return {"status": "ERROR", "error": "No API key provided or configured"}
    
    start = time.time()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500
                },
                timeout=60.0
            )
            elapsed = time.time() - start
            
            if resp.status_code == 200:
                translation = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                return {
                    "status": "OK",
                    "original": text,
                    "translated": translation.strip(),
                    "source_lang": "en",
                    "target_lang": lang,
                    "target_lang_name": lang_name,
                    "model": model,
                    "response_time_ms": int(elapsed * 1000)
                }
            else:
                return {"status": "ERROR", "http_code": resp.status_code, "error": resp.text[:500]}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


@app.get("/api/v1/debug/extract-tasks", tags=["Debug"])
async def debug_extract_tasks(
    transcript: str = "John will finish the report by Friday. Mary needs to call the client tomorrow.",
    model: str = "google/gemma-3-4b-it:free",
    api_key: str = None
):
    """Debug endpoint: Test task extraction
    
    Params:
    - transcript: Meeting transcript text
    - model: OpenRouter model to use
    - api_key: Override API key (optional)
    
    Example: /api/v1/debug/extract-tasks?transcript=Alice%20will%20deploy%20by%20Monday
    """
    if not config.DEBUG_MODE:
        raise HTTPException(status_code=403, detail="Debug mode disabled")
    
    import httpx
    import time
    import json
    
    prompt = f"""Extract action items from this meeting transcript. Return JSON array only:

Transcript: {transcript}

Return format:
[{{"task": "description", "assignee": "name", "deadline": "date or null"}}]

JSON:"""
    
    key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key or len(key) < 10:
        return {"status": "ERROR", "error": "No API key provided or configured"}
    
    start = time.time()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1000
                },
                timeout=60.0
            )
            elapsed = time.time() - start
            
            if resp.status_code == 200:
                content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                # Try to parse JSON from response
                try:
                    # Handle markdown code blocks
                    if "```" in content:
                        content = content.split("```")[1]
                        if content.startswith("json"):
                            content = content[4:]
                    tasks = json.loads(content.strip())
                except:
                    tasks = {"raw_response": content, "parse_error": "Could not parse as JSON"}
                
                return {
                    "status": "OK",
                    "transcript": transcript,
                    "tasks": tasks,
                    "model": model,
                    "response_time_ms": int(elapsed * 1000)
                }
            else:
                return {"status": "ERROR", "http_code": resp.status_code, "error": resp.text[:500]}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


@app.post("/api/v1/debug/transcribe", tags=["Debug"])
async def debug_transcribe(
    audio: UploadFile = File(...),
    language: str = "hi"
):
    """Debug endpoint: Test transcription directly
    
    Params:
    - audio: Audio file to transcribe
    - language: Language hint (hi=Hindi, en=English, auto=auto-detect)
    
    Supports: Sarvam (Hindi), Groq Whisper (multilingual), Deepgram (premium)
    """
    if not config.DEBUG_MODE:
        raise HTTPException(status_code=403, detail="Debug mode disabled")
    
    import tempfile
    import shutil
    import time
    
    # Save uploaded file
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio.filename).suffix) as tmp:
        shutil.copyfileobj(audio.file, tmp)
        tmp_path = tmp.name
    
    try:
        ai_service = get_ai_service()
        start_time = time.time()
        result = await ai_service.transcribe_audio(tmp_path, language=language)
        
        elapsed = time.time() - start_time
        
        return {
            "status": "OK",
            "filename": audio.filename,
            "size_bytes": audio.size,
            "language_requested": language,
            "transcription": result,
            "processing_time_ms": int(elapsed * 1000)
        }
    except Exception as e:
        logger.exception("Debug transcription failed")
        return {"status": "ERROR", "error": str(e)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint - serves frontend"""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return FileResponse(frontend_path)
    return {"message": "Meeting Master API", "version": config.API_VERSION}


@app.get("/api/v1/auth/config", tags=["Auth"])
async def auth_config():
    """Get authentication configuration for frontend.
    Returns Descope project ID and flow ID for the web component.
    """
    return {
        "descope_enabled": True,
        "descope_project_id": config.DESCOPE_PROJECT_ID,
        "descope_flow_id": config.DESCOPE_FLOW_ID,
        "guest_mode_enabled": True,
        "message": "Descope authentication available"
    }


# =============================================================================
# Authentication
# =============================================================================

@app.get("/api/v1/auth/me", tags=["Auth"])
async def get_me(user: dict = Depends(require_auth)):
    """Get current user profile (Descope or guest)"""
    return {
        "user_id": user.get("user_id") or user.get("id", ""),
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "tier": user.get("tier", "FREE"),
        "is_guest": user.get("is_guest", False),
    }


@app.post("/api/v1/auth/refresh", tags=["Auth"])
async def auth_refresh(request: Request):
    """Proxy refresh token to auth-service for new session JWT.
    Called by frontend when Descope session JWT expires.
    """
    import httpx

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    refresh_jwt = body.get("refreshJwt")
    if not refresh_jwt:
        raise HTTPException(status_code=400, detail="Missing refreshJwt")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{config.AUTH_SERVICE_URL}/v1/refresh",
                json={"refreshJwt": refresh_jwt},
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Refresh failed")
        refresh_data = resp.json()
        new_jwt = refresh_data.get("sessionJwt", "")
        logger.info(f"Refresh success: has_sessionJwt={bool(new_jwt)}, token_prefix={new_jwt[:20] if new_jwt else 'NONE'}...")
        return refresh_data
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")


@app.post("/api/v1/auth/descope-login", tags=["Auth"])
async def descope_login(request: Request):
    """Exchange a short-lived Descope session JWT for a long-lived local app JWT.

    Called by the frontend after Descope sign-in succeeds. The Descope sessionJwt
    is validated once via auth-service, then a local JWT (7-day expiry) is issued
    so the user stays logged in across page refreshes without depending on Descope
    token refresh.
    """
    import httpx

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    session_jwt = body.get("sessionJwt")
    if not session_jwt:
        raise HTTPException(status_code=400, detail="Missing sessionJwt")

    # Validate Descope JWT via auth-service
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{config.AUTH_SERVICE_URL}/v1/validate",
                headers={
                    "Authorization": f"Bearer {session_jwt}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Descope token")

    auth_data = resp.json()
    descope_user = auth_data.get("user", {})
    login_id = auth_data.get("loginId", "")

    user_id = descope_user.get("userId", login_id)
    email = login_id or descope_user.get("email", "")
    name = descope_user.get("name") or email.split("@")[0] or "User"

    # Extract tier from user's apps config
    apps = (descope_user.get("customAttributes") or {}).get("apps", {})
    # apps may arrive as a JSON string from auth-service — parse if needed
    if isinstance(apps, str):
        try:
            import json as _json
            apps = _json.loads(apps)
        except (ValueError, TypeError):
            apps = {}
    app_cfg = apps.get(config.APP_NAME_IN_AUTH, {}) if isinstance(apps, dict) else {}
    tier = str(app_cfg.get("tier", "free")).upper() if isinstance(app_cfg, dict) else "FREE"

    # Issue a long-lived local JWT (7 days)
    from datetime import datetime, timedelta
    secret = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET", config.JWT_SECRET_KEY)
    now = datetime.utcnow()
    token_data = {
        "sub": user_id,
        "name": name,
        "email": email,
        "tier": tier,
        "provider": "descope",   # marks this as a Descope-originated local token
        "is_guest": False,
        "exp": now + timedelta(days=7),
    }
    local_token = jwt.encode(token_data, secret, algorithm=config.JWT_ALGORITHM)

    # Upsert local user record
    store = get_store()
    user_doc = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "created_at": now.isoformat(),
        "last_login": now.isoformat(),
        "settings": {},
        "team_members": [],
        "is_guest": False,
    }
    try:
        store.create_user(user_doc)
    except Exception as e:
        logger.warning(f"Failed to upsert Descope user: {e}")

    return {
        "access_token": local_token,
        "token_type": "bearer",
        "expires_in": 7 * 24 * 3600,  # 7 days
        "user": {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture_url": descope_user.get("picture"),
            "is_guest": False,
            "tier": tier,
        },
    }


class GuestAuthRequest(BaseModel):
    device_id: Optional[str] = None
    device_name: Optional[str] = None


@app.post("/api/v1/auth/guest", response_model=TokenResponse, tags=["Auth"])
async def guest_auth(request: GuestAuthRequest = None):
    """Create guest account with temporary token.

    If device_id is provided, the same guest_id is returned on every call with
    that device_id — this allows meeting history to persist across page reloads.
    """
    import uuid
    import hashlib
    from datetime import datetime, timedelta

    # Use device_id to produce a stable guest_id across re-logins
    device_id = (request.device_id if request else None) or ""
    if device_id:
        # Deterministic but opaque: sha256(device_id)[:16]
        stable_hash = hashlib.sha256(device_id.encode()).hexdigest()[:16]
        guest_id = f"guest_{stable_hash}"
    else:
        guest_id = f"guest_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow()
    
    user = {
        "user_id": guest_id,
        "email": "",
        "name": "Guest",
        "created_at": now.isoformat(),
        "last_login": now.isoformat(),
        "settings": {},
        "team_members": [],
        "is_guest": True
    }
    
    # Save guest user locally (optional - for meeting history)
    store = get_store()
    try:
        store.create_user(user)
    except Exception as e:
        logger.warning(f"Failed to save guest user: {e}")
    
    # Generate JWT token
    secret = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET", config.JWT_SECRET_KEY)
    token_data = {
        "sub": guest_id,
        "name": "Guest",
        "email": "",
        "is_guest": True,
        "exp": now + timedelta(hours=24)
    }
    token = jwt.encode(token_data, secret, algorithm=config.JWT_ALGORITHM)
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=86400,  # 24 hours in seconds
        user=UserProfile(
            user_id=guest_id,
            email="",
            name="Guest",
            picture_url=None,
            created_at=now,
            last_login=now
        )
    )


# =============================================================================
# Settings
# =============================================================================

@app.get("/api/v1/settings", response_model=UserSettings, tags=["Settings"])
async def get_settings(user: dict = Depends(require_auth)):
    """Get user settings"""
    store = get_store()
    stored_user = ensure_user_record(user, store) or {}
    settings = dict(stored_user.get("settings") or {})
    return UserSettings(
        profile_name=settings.get("profile_name", stored_user.get("name", "")),
        profile_email=settings.get("profile_email", stored_user.get("email", "")),
        default_language=settings.get("default_language", "en"),
        speaker_diarization=settings.get("speaker_diarization", True),
        team_members=_normalize_settings_team_members(
            settings.get("team_members") or stored_user.get("team_members") or []
        ),
    )


@app.put("/api/v1/settings", response_model=UserSettings, tags=["Settings"])
async def update_settings(updates: UserSettingsUpdate, user: dict = Depends(require_auth)):
    """Update user settings"""
    store = get_store()
    stored_user = ensure_user_record(user, store) or {}
    current_settings = dict(stored_user.get("settings") or {})
    
    if updates.profile_name is not None:
        current_settings["profile_name"] = updates.profile_name
    if updates.profile_email is not None:
        current_settings["profile_email"] = updates.profile_email
    if updates.default_language is not None:
        current_settings["default_language"] = updates.default_language
    if updates.speaker_diarization is not None:
        current_settings["speaker_diarization"] = updates.speaker_diarization
    if updates.team_members is not None:
        current_settings["team_members"] = _normalize_settings_team_members(
            [member.model_dump() for member in updates.team_members]
        )

    user_updates = {"settings": current_settings}

    if updates.profile_name is not None:
        user_updates["name"] = updates.profile_name
    if updates.profile_email is not None:
        user_updates["email"] = updates.profile_email
    if updates.team_members is not None:
        user_updates["team_members"] = current_settings["team_members"]

    store.update_user(user["user_id"], user_updates)

    return UserSettings(
        profile_name=current_settings.get("profile_name", user_updates.get("name", stored_user.get("name", ""))),
        profile_email=current_settings.get("profile_email", user_updates.get("email", stored_user.get("email", ""))),
        default_language=current_settings.get("default_language", "en"),
        speaker_diarization=current_settings.get("speaker_diarization", True),
        team_members=current_settings.get("team_members", []),
    )


# =============================================================================
# Team Management
# =============================================================================

@app.get("/api/v1/team", response_model=List[TeamMember], tags=["Team"])
async def get_team(user: dict = Depends(require_auth)):
    """Get user's team members"""
    store = get_store()
    ensure_user_record(user, store)
    members = store.get_team_members(user["user_id"])
    return [TeamMember(**m) for m in members]


@app.post("/api/v1/team", response_model=TeamMember, tags=["Team"])
async def add_team_member(member: TeamMemberCreate, user: dict = Depends(require_auth)):
    """Add team member"""
    store = get_store()
    ensure_user_record(user, store)
    
    member_data = {
        "name": member.name,
        "email": member.email,
        "added_at": datetime.utcnow().isoformat()
    }
    
    success = store.add_team_member(user["user_id"], member_data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to add team member")
    
    return TeamMember(**member_data)


@app.delete("/api/v1/team/{email}", response_model=SuccessResponse, tags=["Team"])
async def remove_team_member(email: str, user: dict = Depends(require_auth)):
    """Remove team member"""
    store = get_store()
    ensure_user_record(user, store)
    success = store.remove_team_member(user["user_id"], email)
    
    if not success:
        raise HTTPException(status_code=404, detail="Team member not found")
    
    return SuccessResponse(success=True, message="Team member removed")


# =============================================================================
# Meetings
# =============================================================================

@app.post("/api/v1/meetings/upload", tags=["Meetings"])
async def upload_meeting(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(None),
    transcript: str = Form(None),
    title: str = Form(None),
    attendee_emails: str = Form("[]"),  # JSON array
    user: dict = Depends(get_current_user)
):
    """Upload audio file or transcript for processing."""
    import json
    
    if not audio and not transcript:
        raise HTTPException(status_code=400, detail="Either audio file or transcript required")
    
    store = get_store()
    stored_user = ensure_user_record(user, store) or {}
    meeting_id = str(uuid.uuid4())
    now = datetime.utcnow()
    
    # Parse attendee emails
    try:
        attendees = json.loads(attendee_emails)
    except json.JSONDecodeError:
        attendees = []
    
    # Save audio file if provided
    audio_url = None
    if audio:
        # Validate file
        ext = audio.filename.split(".")[-1].lower() if audio.filename else "webm"
        if ext not in config.ALLOWED_AUDIO_FORMATS:
            raise HTTPException(status_code=400, detail=f"Invalid audio format. Allowed: {config.ALLOWED_AUDIO_FORMATS}")
        
        # Save file
        audio_path = UPLOAD_DIR / f"{meeting_id}.{ext}"
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)
        audio_url = str(audio_path)
    
    # Create meeting record
    meeting_data = {
        "meeting_id": meeting_id,
        "user_id": stored_user.get("user_id", (user or {}).get("user_id", "anonymous")),
        "title": title or f"Meeting - {now.strftime('%Y-%m-%d %H:%M')}",
        "date": now.isoformat(),
        "audio_url": audio_url,
        "raw_transcript": transcript,
        "status": ProcessingStatus.PENDING.value,
        "attendees": [
            {"speaker_id": f"RECIPIENT_{i + 1}", "email": e, "identified": True}
            for i, e in enumerate(attendees) if e
        ],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    }
    
    store.create_meeting(meeting_data)
    
    processing_settings = dict(stored_user.get("settings") or {})

    background_tasks.add_task(
        process_meeting_task,
        meeting_id,
        stored_user.get("user_id", (user or {}).get("user_id", "anonymous")),
        processing_settings
    )
    
    return {
        "meeting_id": meeting_id,
        "status": ProcessingStatus.PENDING.value,
        "message": "Meeting uploaded. Processing started."
    }


@app.post("/api/v1/meetings/process-text", response_model=Meeting, tags=["Meetings"])
async def process_text_meeting(
    request: MeetingTextProcessRequest,
    user: dict = Depends(get_current_user)
):
    """Process literal transcript text immediately and return results.
    
    When config.USE_N8N_WEBHOOKS is True, wraps the text as a single-speaker
    payload and sends it through the AISummarization webhook (same as brd-agent's
    /api/transcript-summary). Otherwise uses the internal LLM pipeline.
    """
    store = get_store()
    stored_user = ensure_user_record(user, store) or {}
    
    meeting_id = str(uuid.uuid4())
    now = datetime.utcnow()
    title = request.title or f"Text Analysis - {now.strftime('%Y-%m-%d %H:%M')}"
    
    # Create meeting record
    meeting_data = {
        "meeting_id": meeting_id,
        "user_id": stored_user.get("user_id", (user or {}).get("user_id", "anonymous")),
        "title": title,
        "date": now.isoformat(),
        "raw_transcript": request.transcript,
        "status": ProcessingStatus.PROCESSING.value,
        "processing_progress": 18,
        "processing_stage": "reading_transcript",
        "processing_message": "Reading the transcript and preparing the summary.",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "attendees": _coerce_text_request_attendees(request),
        "transcript_en": None,
        "transcript_hi": None,
        "transcript_hinglish": None,
        "automation": {
            "dispatch_success": False,
            "auto_sent_email": False,
            "auto_scheduled_calendar": False,
            "baseline_timestamp": now.isoformat(),
            "recipients": [str(email) for email in request.attendee_emails],
            "source": "meeting-master-auto-dispatch",
            "error": None,
        },
    }
    store.create_meeting(meeting_data)
    
    try:
        if config.USE_N8N_WEBHOOKS:
            # --- n8n Webhook Pipeline ---
            # Wrap raw text as single-speaker payload (same as brd-agent)
            speaker_map = _build_text_speaker_map(request.transcript, participants=request.participants)
            _update_processing_state(
                meeting_id,
                progress=58,
                stage="summarizing",
                message="Pulling the summary, decisions, and action items from the transcript.",
            )
            summary_data = await summarize_transcript_webhook(speaker_map)
            if not summary_data:
                # AISummarization webhook is intermittently flaky for some
                # transcripts. The transcript itself is real — fall back to
                # deterministic transcript-derived extraction so process-text
                # still returns a complete meeting record. Same approach as
                # the audio path (process_meeting_task).
                logger.warning(
                    f"[process-text] AISummarization empty for meeting "
                    f"{meeting_id}; building updates from transcript directly"
                )
                updates = _fallback_process_transcript(
                    request.transcript,
                    now,
                    title,
                    participants=request.participants,
                )
                updates["raw_transcript"] = request.transcript
                updates["model_used"] = "n8n-transcribe+local-summary-fallback"
                updates["warning"] = (
                    "AI summarization (AISummarization webhook) was unavailable; "
                    "tasks and MoM were extracted from the real transcript using a deterministic parser."
                )
            else:
                updates = map_webhook_to_meeting_updates(
                    speaker_map=speaker_map,
                    summary_data=summary_data,
                    meeting_date=now,
                    title=title,
                )
                updates = _enrich_sparse_meeting_updates(
                    request.transcript,
                    now,
                    title,
                    updates,
                    participants=request.participants,
                )
            updates.update({
                "status": ProcessingStatus.COMPLETED.value,
                "processed_at": datetime.utcnow().isoformat(),
                "model_used": updates.get("model_used", "n8n-webhook-pipeline"),
                "processing_progress": 100,
                "processing_stage": "completed",
                "processing_message": "Your meeting summary is ready to review.",
            })
            updates["attendees"] = _merge_attendees(meeting_data["attendees"], updates.get("attendees"))
        else:
            # --- Internal AI Pipeline ---
            _update_processing_state(
                meeting_id,
                progress=58,
                stage="summarizing",
                message="Understanding the transcript and generating follow-up items.",
            )
            ai = get_ai_service()
            result = await ai.process_transcript(
                transcript=request.transcript,
                meeting_date=now,
                uploader_name=stored_user.get("name", user.get("name", "User") if user else "User"),
                team_members=_resolve_user_team_members(stored_user)
            )
            updates = {
                "status": ProcessingStatus.COMPLETED.value,
                "transcript_en": result.transcript_en,
                "transcript_hi": result.transcript_hi,
                "transcript_hinglish": result.transcript_hinglish,
                "attendees": [a.dict() for a in result.attendees],
                "tasks": [t.dict() for t in result.tasks],
                "calendar_events": [e.dict() for e in result.calendar_events],
                "mail": result.mail.dict(),
                "summary": result.summary,
                "tags": result.tags,
                "sentiment": result.sentiment,
                "confidence": result.confidence,
                "processed_at": datetime.utcnow().isoformat(),
                "processing_progress": 100,
                "processing_stage": "completed",
                "processing_message": "Your meeting summary is ready to review.",
            }
            updates["attendees"] = _merge_attendees(meeting_data["attendees"], updates.get("attendees"))

        # Backfill an English translation of the raw transcript when it's
        # non-English (Hindi / Tamil / Telugu / etc). Idempotent.
        if not updates.get("raw_transcript"):
            updates["raw_transcript"] = request.transcript
        _update_processing_state(
            meeting_id,
            progress=92,
            stage="translating",
            message="Translating the transcript to English for the second tab.",
        )
        updates = await _ensure_english_translation(updates)

        dispatching_updates = {
            **updates,
            "status": ProcessingStatus.PROCESSING.value,
            "processing_progress": 96,
            "processing_stage": "dispatching",
            "processing_message": "Dispatching follow-up email and calendar actions.",
        }
        updated = store.update_meeting(meeting_id, dispatching_updates)
        updated = _refresh_meeting_metrics(updated, store=store)
        updated = await _auto_dispatch_meeting_outputs(meeting_id, stored_user, store=store)
        finalized = store.update_meeting(meeting_id, {
            "status": ProcessingStatus.COMPLETED.value,
            "processing_progress": 100,
            "processing_stage": "completed",
            "processing_message": "Your meeting is ready to review.",
        })
        finalized = _refresh_meeting_metrics(finalized, store=store)
        return Meeting(**finalized)
        
    except Exception as e:
        logger.error(f"Text processing failed: {e}")
        store.update_meeting(meeting_id, {
            "status": ProcessingStatus.FAILED.value,
            "error_message": str(e),
            "processing_stage": "failed",
            "processing_message": str(e),
        })
        raise HTTPException(status_code=500, detail=str(e))


async def process_meeting_task(meeting_id: str, user_id: str, settings: dict):
    """Background task to process meeting.
    
    When config.USE_N8N_WEBHOOKS is True, uses the n8n webhook pipeline:
      1. transcribe-audio webhook → speaker-separated transcript
      2. AISummarization webhook  → MOM + Tasks + Calendar
    Otherwise falls back to the internal STT + LLM pipeline.
    """
    import asyncio
    import traceback
    
    store = get_store()
    logger.info(f"Starting background processing for meeting {meeting_id}")
    
    try:
        _update_processing_state(
            meeting_id,
            progress=10,
            stage="queued",
            message="Preparing your meeting workspace.",
        )
        
        meeting = store.get_meeting(meeting_id)
        if not meeting:
            logger.error(f"Meeting {meeting_id} not found in database")
            return
        
        start_time = datetime.utcnow()
        meeting_title = meeting.get("title", "Meeting")
        meeting_date = datetime.fromisoformat(meeting["date"])

        # =====================================================================
        # n8n Webhook Pipeline (primary when USE_N8N_WEBHOOKS=true)
        # =====================================================================
        if config.USE_N8N_WEBHOOKS:
            logger.info(f"Using n8n webhook pipeline for meeting {meeting_id}")
            
            # Step 1: Transcribe audio if needed
            speaker_map = {}
            transcript = meeting.get("raw_transcript")
            
            if not transcript and meeting.get("audio_url"):
                logger.info(f"[Webhook] Transcribing audio for meeting {meeting_id}")
                _update_processing_state(
                    meeting_id,
                    progress=28,
                    stage="transcribing",
                    message="Transcribing the recording and separating speakers.",
                )
                speaker_map = await transcribe_audio_webhook(meeting["audio_url"])
                if not speaker_map:
                    raise Exception("Transcription webhook returned empty result")
            elif transcript:
                # Wrap existing text as single-speaker payload for summarization
                _update_processing_state(
                    meeting_id,
                    progress=28,
                    stage="reading_transcript",
                    message="Reading the transcript and getting it ready for analysis.",
                )
                attendee_names = [
                    str(attendee.get("name") or "").strip()
                    for attendee in (meeting.get("attendees") or [])
                    if isinstance(attendee, dict) and str(attendee.get("name") or "").strip()
                ]
                speaker_map = _build_text_speaker_map(transcript, participants=attendee_names)
            else:
                raise Exception("No audio file or transcript available")
            
            # Step 2: Summarize transcript via webhook
            logger.info(f"[Webhook] Summarizing transcript for meeting {meeting_id}")
            _update_processing_state(
                meeting_id,
                progress=60,
                stage="summarizing",
                message="Finding the summary, decisions, and key moments.",
            )
            summary_data = await summarize_transcript_webhook(speaker_map)

            participant_names = [
                str(attendee.get("name") or "").strip()
                for attendee in (meeting.get("attendees") or [])
                if isinstance(attendee, dict) and str(attendee.get("name") or "").strip()
            ]
            transcript_text = _speaker_map_to_transcript_text(speaker_map)

            if not summary_data:
                # AISummarization unreachable / errored (commonly seen when
                # the downstream Groq node rejects a category enum or 500s
                # on short Hindi clips). Sarvam transcription succeeded — so
                # fall back to deterministic extraction. The regex extractor
                # works best on English, so translate the speaker_map FIRST
                # and run extraction on the English version. This produces
                # real tasks/events from the actual meeting content instead
                # of zero results when the source is non-English.
                logger.warning(
                    f"[Webhook] AISummarization returned empty for meeting "
                    f"{meeting_id}; translating then extracting locally"
                )
                _update_processing_state(
                    meeting_id,
                    progress=84,
                    stage="drafting_outputs",
                    message="AI summary unavailable; translating and extracting actions locally.",
                )

                english_transcript = transcript_text
                if _looks_non_english(transcript_text):
                    translated = await _translate_via_brd_agent(transcript_text, target_language="English")
                    if translated:
                        english_transcript = translated

                updates = _fallback_process_transcript(
                    english_transcript,
                    meeting_date,
                    meeting_title,
                    participants=participant_names,
                )
                # Preserve the original speaker-tagged Hindi transcript and
                # stamp the English version separately for the UI's "English"
                # tab. raw_transcript = native, transcript_en = translated.
                updates["raw_transcript"] = transcript_text
                updates["transcript_en"] = english_transcript
                updates["model_used"] = "n8n-transcribe+local-summary-fallback"
                updates["warning"] = (
                    "AI summarization (AISummarization webhook) was unavailable; "
                    "tasks and MoM were extracted from the translated transcript using a deterministic parser."
                )
            else:
                # Step 3: Map webhook output to meeting model fields
                _update_processing_state(
                    meeting_id,
                    progress=84,
                    stage="drafting_outputs",
                    message="Building tasks, calendar suggestions, and the follow-up email draft.",
                )
                updates = map_webhook_to_meeting_updates(
                    speaker_map=speaker_map,
                    summary_data=summary_data,
                    meeting_date=meeting_date,
                    title=meeting_title,
                )
                updates = _enrich_sparse_meeting_updates(
                    transcript_text,
                    meeting_date,
                    meeting_title,
                    updates,
                    participants=participant_names,
                )

            processing_time = (datetime.utcnow() - start_time).total_seconds()
            updates.update({
                "status": ProcessingStatus.PROCESSING.value,
                "processed_at": datetime.utcnow().isoformat(),
                "model_used": updates.get("model_used", "n8n-webhook-pipeline"),
                "processing_time_seconds": processing_time,
                "processing_progress": 96,
                "processing_stage": "dispatching",
                "processing_message": "Dispatching follow-up email and calendar actions.",
            })
            updates["attendees"] = _merge_attendees(meeting.get("attendees"), updates.get("attendees"))

            # Ensure we have an English-translated transcript when the raw
            # transcript is in another language (Hindi, Tamil, Telugu, etc).
            # The native language transcript stays in raw_transcript; the
            # translated version is stored in transcript_en for the UI.
            _update_processing_state(
                meeting_id,
                progress=92,
                stage="translating",
                message="Translating the transcript to English for the second tab.",
            )
            updates = await _ensure_english_translation(updates)

            updated_meeting = store.update_meeting(meeting_id, updates)
            updated_meeting = _refresh_meeting_metrics(updated_meeting, store=store)
            stored_user = store.get_user_by_id(user_id) if user_id else None
            await _auto_dispatch_meeting_outputs(meeting_id, stored_user, store=store)
            finalized = store.update_meeting(meeting_id, {
                "status": ProcessingStatus.COMPLETED.value,
                "processing_progress": 100,
                "processing_stage": "completed",
                "processing_message": "Your meeting is ready to review.",
            })
            _refresh_meeting_metrics(finalized, store=store)
            logger.info(f"Meeting {meeting_id} processed via webhooks in {processing_time:.2f}s")
            return

        # =====================================================================
        # Internal AI Pipeline (fallback when USE_N8N_WEBHOOKS=false)
        # =====================================================================
        logger.info(f"Using internal AI pipeline for meeting {meeting_id}")
        _update_processing_state(
            meeting_id,
            progress=22,
            stage="analyzing",
            message="Preparing the meeting for analysis.",
        )
        
        if settings and any(settings.get(key) for key in ["model_provider", "api_keys", "model"]):
            logger.info("Ignoring legacy per-user LLM settings and using the server-managed AI configuration")

        ai = get_ai_service()
        provider_label = ai.provider.value if isinstance(ai.provider, ModelProvider) else str(ai.provider)
        logger.info(f"Using provider: {provider_label}, model: {ai.model}")
        
        # Transcribe audio if needed
        transcript = meeting.get("raw_transcript")
        duration = None
        
        if not transcript and meeting.get("audio_url"):
            logger.info(f"Transcribing audio for meeting {meeting_id}")
            _update_processing_state(
                meeting_id,
                progress=40,
                stage="transcribing",
                message="Transcribing the recording and separating speakers.",
            )
            result = await ai.transcribe_audio(meeting["audio_url"])
            transcript = result["raw_text"]
            duration = result.get("duration_seconds")
            logger.info(f"Transcription complete, length: {len(transcript)} chars")
        
        if not transcript:
            raise Exception("No transcript available")
        
        # Get user for team members
        user = store.get_user_by_id(user_id)
        team_members = _resolve_user_team_members(user)
        
        # Process transcript
        logger.info(f"Processing transcript with AI for meeting {meeting_id}")
        _update_processing_state(
            meeting_id,
            progress=72,
            stage="summarizing",
            message="Finding the summary, tasks, and follow-up details.",
        )
        result = await ai.process_transcript(
            transcript=transcript,
            meeting_date=meeting_date,
            duration_seconds=duration or meeting.get("duration_seconds"),
            uploader_name=user.get("name", "User") if user else "User",
            team_members=team_members
        )
        logger.info(f"AI processing complete for meeting {meeting_id}")
        
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Update meeting with results
        updates = {
            "status": ProcessingStatus.PROCESSING.value,
            "raw_transcript": transcript,
            "transcript_en": result.transcript_en,
            "transcript_hi": result.transcript_hi,
            "transcript_hinglish": result.transcript_hinglish,
            "attendees": [a.dict() for a in result.attendees],
            "tasks": [t.dict() for t in result.tasks],
            "calendar_events": [e.dict() for e in result.calendar_events],
            "mail": result.mail.dict(),
            "summary": result.summary,
            "tags": result.tags,
            "sentiment": result.sentiment,
            "confidence": result.confidence,
            "processed_at": datetime.utcnow().isoformat(),
            "model_used": f"{provider_label}/{ai.model}" if ai.model else provider_label,
            "processing_time_seconds": processing_time,
            "duration_seconds": duration,
            "processing_progress": 96,
            "processing_stage": "dispatching",
            "processing_message": "Dispatching follow-up email and calendar actions.",
            "attendees": _merge_attendees(meeting.get("attendees"), [a.dict() for a in result.attendees]),
        }

        # Backfill transcript_en when the raw transcript is non-English and
        # the internal AI service didn't populate it.
        _update_processing_state(
            meeting_id,
            progress=92,
            stage="translating",
            message="Translating the transcript to English for the second tab.",
        )
        updates = await _ensure_english_translation(updates)

        updated_meeting = store.update_meeting(meeting_id, updates)
        updated_meeting = _refresh_meeting_metrics(updated_meeting, store=store)
        stored_user = store.get_user_by_id(user_id) if user_id else None
        await _auto_dispatch_meeting_outputs(meeting_id, stored_user, store=store)
        finalized = store.update_meeting(meeting_id, {
            "status": ProcessingStatus.COMPLETED.value,
            "processing_progress": 100,
            "processing_stage": "completed",
            "processing_message": "Your meeting is ready to review.",
        })
        _refresh_meeting_metrics(finalized, store=store)
        logger.info(f"Meeting {meeting_id} processed successfully in {processing_time:.2f}s")
    
    except Exception as e:
        logger.error(f"Error processing meeting {meeting_id}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        store.update_meeting(meeting_id, {
            "status": ProcessingStatus.FAILED.value,
            "error_message": str(e),
            "processing_stage": "failed",
            "processing_message": str(e),
        })


@app.get("/api/v1/meetings/{meeting_id}", response_model=Meeting, tags=["Meetings"])
async def get_meeting(meeting_id: str, user: dict = Depends(get_current_user)):
    """Get meeting by ID"""
    store = get_store()
    meeting = store.get_meeting(meeting_id)
    
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    # Skip ownership check when no auth (guest/anonymous access)
    if user and meeting["user_id"] != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return Meeting(**meeting)


@app.get("/api/v1/meetings/{meeting_id}/kpis", tags=["Meetings"])
async def get_meeting_kpis(meeting_id: str, user: dict = Depends(get_current_user)):
    """Get execution KPIs for a single meeting."""
    store = get_store()
    meeting = store.get_meeting(meeting_id)

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if user and meeting["user_id"] != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Access denied")

    updated = _refresh_meeting_metrics(meeting, store=store)
    return (updated or meeting).get("kpis") or compute_meeting_kpis(updated or meeting)


@app.post("/api/v1/meetings/{meeting_id}/generate-brd", response_model=SuccessResponse, tags=["Meetings"])
async def generate_brd_from_meeting(
    meeting_id: str,
    request: GenerateMeetingBRDRequest,
    user: dict = Depends(get_current_user)
):
    """Generate a new BRD in RequireWise from a real meeting record."""
    store = get_store()
    meeting = store.get_meeting(meeting_id)

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if user and meeting["user_id"] != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Access denied")

    meeting = _refresh_meeting_metrics(meeting, store=store) or meeting
    filename = _slugify_meeting_title(request.filename or meeting.get("title") or meeting_id)
    prompt = _build_brd_generation_prompt(meeting)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config.BRD_AGENT_API_BASE}/new-brd",
                json={
                    "filename": filename,
                    "text": prompt,
                    "search_query": " | ".join(
                        part for part in [meeting.get("title") or "", meeting.get("summary") or ""] if str(part).strip()
                    )[:400],
                },
                timeout=420.0,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"RequireWise bridge unavailable: {exc}") from exc

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    if response.status_code != 200 or not data.get("success", True):
        raise HTTPException(
            status_code=502,
            detail=(data.get("error") if isinstance(data, dict) else None) or f"BRD agent returned {response.status_code}",
        )

    return SuccessResponse(
        message="BRD generated in RequireWise",
        data={
            "filename": filename,
            "brd_agent_base": config.BRD_AGENT_API_BASE,
            "response": data,
        },
    )


@app.get("/api/v1/meetings", response_model=MeetingListResponse, tags=["Meetings"])
async def list_meetings(
    page: int = 1,
    limit: int = 10,
    search: str = None,
    status: str = None,
    user: dict = Depends(get_current_user)
):
    """List user's meetings"""
    store = get_store()
    result = store.list_meetings(
        user_id=(user or {}).get("user_id", "anonymous"),
        page=page,
        limit=limit,
        search=search,
        status=status
    )
    return MeetingListResponse(**result)


@app.get("/api/v1/kpis/overview", response_model=KPIOverview, tags=["Insights"])
async def get_kpi_overview(user: dict = Depends(get_current_user)):
    """Get portfolio-wide execution KPIs for the current user."""
    store = get_store()
    result = store.list_meetings(
        user_id=(user or {}).get("user_id", "anonymous"),
        page=1,
        limit=1000,
    )
    meeting_ids = [meeting.get("meeting_id") for meeting in result.get("meetings", [])]
    meetings = [store.get_meeting(meeting_id) for meeting_id in meeting_ids if meeting_id]
    overview = compute_portfolio_kpis([meeting for meeting in meetings if meeting])
    return KPIOverview(**overview)


@app.get("/api/v1/kpis/business-overview", tags=["Insights"])
async def get_business_kpi_overview(limit: int = 12):
    """Get workspace-wide execution KPIs across all stored meetings for dashboard surfaces."""
    store = get_store()
    result = store.list_all_meetings(page=1, limit=max(limit, 1))
    meeting_ids = [meeting.get("meeting_id") for meeting in result.get("meetings", [])]
    meetings = [store.get_meeting(meeting_id) for meeting_id in meeting_ids if meeting_id]
    overview = compute_portfolio_kpis([meeting for meeting in meetings if meeting])
    return {
        "overview": overview,
        "meetings": meetings,
        "total": result.get("total", 0),
    }


@app.put("/api/v1/meetings/{meeting_id}", response_model=Meeting, tags=["Meetings"])
async def update_meeting(meeting_id: str, updates: MeetingUpdate, user: dict = Depends(get_current_user)):
    """Update meeting (edit tasks, calendar, etc.)"""
    store = get_store()
    
    meeting = store.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    if user and meeting["user_id"] != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Convert updates to dict, excluding None values
    update_data = updates.dict(exclude_none=True)
    
    # Convert nested objects
    if "attendees" in update_data:
        update_data["attendees"] = [a.dict() if hasattr(a, 'dict') else a for a in update_data["attendees"]]
    if "tasks" in update_data:
        update_data["tasks"] = [t.dict() if hasattr(t, 'dict') else t for t in update_data["tasks"]]
    if "calendar_events" in update_data:
        update_data["calendar_events"] = [e.dict() if hasattr(e, 'dict') else e for e in update_data["calendar_events"]]
    if "mail" in update_data and update_data["mail"]:
        update_data["mail"] = update_data["mail"].dict() if hasattr(update_data["mail"], 'dict') else update_data["mail"]
    
    updated = store.update_meeting(meeting_id, update_data)
    updated = _refresh_meeting_metrics(updated, store=store)
    return Meeting(**updated)


@app.delete("/api/v1/meetings/{meeting_id}", response_model=SuccessResponse, tags=["Meetings"])
async def delete_meeting(meeting_id: str, user: dict = Depends(get_current_user)):
    """Delete meeting"""
    store = get_store()
    
    meeting = store.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    if user and meeting["user_id"] != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Delete audio file if exists
    if meeting.get("audio_url"):
        audio_path = Path(meeting["audio_url"])
        if audio_path.exists():
            audio_path.unlink()
    
    store.delete_meeting(meeting_id)
    return SuccessResponse(success=True, message="Meeting deleted")


@app.post("/api/v1/meetings/{meeting_id}/process", response_model=ProcessingStatusResponse, tags=["Meetings"])
async def process_meeting(
    meeting_id: str,
    request: MeetingProcessRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user)
):
    """Manually trigger meeting processing"""
    store = get_store()
    
    meeting = store.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    if user and meeting["user_id"] != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    stored_user = ensure_user_record(user, store) or {}
    settings = dict(stored_user.get("settings") or {})
    
    # Start processing
    background_tasks.add_task(
        process_meeting_task,
        meeting_id,
        stored_user.get("user_id", (user or {}).get("user_id", "anonymous")),
        settings
    )
    
    return ProcessingStatusResponse(
        meeting_id=meeting_id,
        status=ProcessingStatus.PROCESSING,
        progress=10,
        stage="queued",
        message="Processing started"
    )


@app.get("/api/v1/meetings/{meeting_id}/status", response_model=ProcessingStatusResponse, tags=["Meetings"])
async def get_meeting_status(meeting_id: str, user: dict = Depends(get_current_user)):
    """Get meeting processing status"""
    store = get_store()
    
    meeting = store.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    # Skip ownership check when no auth (guest/anonymous access)
    if user and meeting["user_id"] != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return ProcessingStatusResponse(
        meeting_id=meeting_id,
        status=ProcessingStatus(meeting["status"]),
        progress=meeting.get("processing_progress"),
        stage=meeting.get("processing_stage"),
        message=meeting.get("processing_message"),
        error=meeting.get("error_message")
    )


# =============================================================================
# Calendar Integration (Placeholder)
# =============================================================================

@app.post("/api/v1/meetings/{meeting_id}/google-tools", tags=["Google Tools"])
async def trigger_meeting_google_tools(
    meeting_id: str,
    user: dict = Depends(get_current_user)
):
    """Trigger Google Workspace integrations for a processed meeting.
    
    Uses the google_tool_event n8n webhook to:
    - Schedule Google Calendar events from the meeting's calendar_events
    - Email the MOM to all attendee recipients
    - Log extracted tasks
    
    Requires the meeting to be in COMPLETED status with extracted data.
    """
    store = get_store()
    meeting = store.get_meeting(meeting_id)
    
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if user and meeting.get("user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorized")
    if meeting.get("status") != ProcessingStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Meeting must be processed first. Current status: {meeting.get('status')}"
        )
    
    # Collect recipient emails from attendees
    recipients = []
    for attendee in meeting.get("attendees", []):
        email = attendee.get("email")
        if email:
            recipients.append(email)
    
    # Also include mail 'to' recipients if present
    mail_data = meeting.get("mail", {})
    if isinstance(mail_data, dict):
        for email in mail_data.get("to", []):
            if email and email not in recipients:
                recipients.append(email)
    
    if not recipients:
        raise HTTPException(
            status_code=400,
            detail="No recipient emails found. Add attendee emails before triggering Google Tools."
        )
    
    google_tools_payload = _build_google_tools_payload(
        meeting,
        recipients=recipients,
        fallback_body=mail_data.get("body") if isinstance(mail_data, dict) else None,
        fallback_owner=(user or {}).get("name"),
    )
    
    # Call the Google Tools webhook
    result = await trigger_google_tools_webhook(
        recipients=google_tools_payload["recipients"],
        calendar=google_tools_payload["calender"],
        tasks=google_tools_payload["Task"],
        mom=google_tools_payload["MOM"],
    )
    
    if result.get("success"):
        # Update mail.sent status in the meeting record
        updated = store.update_meeting(meeting_id, {
            "mail": {**mail_data, "sent": True, "sent_at": datetime.utcnow().isoformat()},
            "automation": {
                **(meeting.get("automation") or {}),
                "dispatch_success": True,
                "auto_sent_email": True,
                "auto_scheduled_calendar": bool(google_tools_payload["calender"]),
                "dispatched_at": datetime.utcnow().isoformat(),
                "recipients": recipients,
                "source": "manual-google-tools",
                "error": None,
            }
        })
        _refresh_meeting_metrics(updated, store=store)
    
    return result


@app.post("/api/v1/meetings/{meeting_id}/send-email", response_model=SuccessResponse, tags=["Email"])
async def send_meeting_email(
    meeting_id: str,
    request: MeetingEmailSendRequest,
    user: dict = Depends(get_current_user)
):
    """Send the edited meeting email via the configured workflow webhook."""
    store = get_store()
    meeting = store.get_meeting(meeting_id)

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if user and meeting.get("user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorized")

    recipients = [email.strip() for email in request.to.split(",") if email.strip()]
    if not recipients:
        raise HTTPException(status_code=400, detail="At least one recipient email is required")
    if not request.subject.strip():
        raise HTTPException(status_code=400, detail="Email subject is required")
    if not request.body.strip():
        raise HTTPException(status_code=400, detail="Email body is required")

    webhook_payload = _build_google_tools_payload(
        meeting,
        recipients=recipients,
        fallback_body=request.body.strip(),
        fallback_owner=(user or {}).get("name"),
    )

    result = await trigger_email_send_webhook(webhook_payload)
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("message", "Email webhook failed"))

    mail_data = dict(meeting.get("mail") or {})
    sent_at = datetime.utcnow().isoformat()
    mail_data.update({
        "subject": request.subject.strip(),
        "to": recipients,
        "cc": request.cc or [],
        "body": request.body.strip(),
        "sent": True,
        "sent_at": sent_at,
    })
    store.update_meeting(meeting_id, {
        "mail": mail_data,
        "automation": {
            **(meeting.get("automation") or {}),
            "dispatch_success": True,
            "auto_sent_email": True,
            "auto_scheduled_calendar": bool((meeting.get("calendar_events") or [])),
            "dispatched_at": sent_at,
            "recipients": recipients,
            "source": "manual-email-send",
            "error": None,
        },
        "updated_at": sent_at,
    })

    refreshed = store.get_meeting(meeting_id)
    _refresh_meeting_metrics(refreshed, store=store)

    return SuccessResponse(
        message="Email sent via workflow webhook",
        data={
            "webhook_url": config.N8N_WEBHOOK_SEND_EMAIL,
            "request_method": "POST",
            "request_body": webhook_payload,
            "webhook_response": result.get("response"),
        },
    )


@app.get("/api/v1/calendar/authorize", tags=["Calendar"])
async def get_calendar_auth_url(user: dict = Depends(require_auth)):
    """Google Calendar OAuth is handled by the n8n side via google_tool_event.

    Calendar event creation (POST /calendar/events) goes through n8n with the
    pre-authorized service account, so per-user OAuth at this layer is not
    used. Returning 501 to make the absence of a real OAuth URL explicit
    instead of handing the client a fake authorize URL.
    """
    raise HTTPException(
        status_code=501,
        detail="Per-user Google Calendar OAuth is not implemented here. "
               "Calendar events are dispatched via the n8n google_tool_event "
               "webhook using a service account.",
    )


@app.post("/api/v1/calendar/events", response_model=List[CalendarEventResult], tags=["Calendar"])
async def create_calendar_events(request: CalendarEventCreate, user: dict = Depends(get_current_user)):
    """Create Google Calendar events for one or more events on a stored meeting.

    Wired through the Stage 3 google_tool_event webhook (the same path
    auto-dispatch uses), so it actually schedules real events in the destination
    Google Calendar instead of returning the old placeholder error.
    """
    store = get_store()
    meeting = store.get_meeting(request.meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if user and meeting.get("user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorized")

    requested_ids = set(request.event_ids or [])
    all_events = [e for e in (meeting.get("calendar_events") or []) if isinstance(e, dict)]
    selected = [e for e in all_events if not requested_ids or e.get("id") in requested_ids]

    if not selected:
        return [
            CalendarEventResult(
                event_id=eid,
                google_event_id="not-created",
                success=False,
                error="Event not found on this meeting",
            )
            for eid in (request.event_ids or [])
        ]

    calendar_payload = [
        {
            "title": e.get("title") or "Untitled event",
            "time": e.get("start_datetime") or e.get("time") or "",
            "end": e.get("end_datetime") or "",
            "description": e.get("description") or "",
        }
        for e in selected
    ]
    recipients = _collect_dispatch_recipients(meeting, None)

    result = await trigger_google_tools_webhook(
        recipients=recipients,
        calendar=calendar_payload,
        tasks=[],
        mom=[{"topic": meeting.get("title") or "Calendar dispatch",
              "discussion_summary": "Calendar events scheduled via API.",
              "decisions": "", "owner": ""}],
    )

    success = bool(result.get("success"))
    error_msg = None if success else (result.get("message") or "Calendar webhook failed")
    return [
        CalendarEventResult(
            event_id=e.get("id") or "",
            google_event_id=e.get("google_event_id") or "scheduled",
            success=success,
            error=error_msg,
        )
        for e in selected
    ]


# =============================================================================
# Translation + File Search (thin proxy to brd-agent so the meeting UI can
# trigger LLM translation and ingest emails into Gemini File Search from
# inside the meeting workspace)
# =============================================================================


@app.post("/api/v1/meetings/{meeting_id}/translate", tags=["Meetings"])
async def translate_meeting_transcript(meeting_id: str, user: dict = Depends(get_current_user)):
    """Force a re-run of the transcript-to-English translation for a meeting.

    Pulls the meeting's raw_transcript, calls the brd-agent /api/translate
    endpoint, and persists the result on `transcript_en`.
    """
    store = get_store()
    meeting = store.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if user and meeting.get("user_id") and meeting["user_id"] != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorized for this meeting")

    raw = (meeting.get("raw_transcript") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Meeting has no raw transcript to translate")

    translated = await _translate_via_brd_agent(raw, target_language="English")
    if not translated:
        raise HTTPException(status_code=502, detail="Translation upstream call failed")

    store.update_meeting(meeting_id, {
        "transcript_en": translated,
        "updated_at": datetime.utcnow().isoformat(),
    })
    return {"success": True, "transcript_en_length": len(translated)}


@app.get("/api/v1/filesearch/status", tags=["FileSearch"])
async def filesearch_status_proxy():
    url = f"{config.BRD_AGENT_API_BASE.rstrip('/')}/filesearch/status"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            return r.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"filesearch status proxy failed: {exc}")


@app.get("/api/v1/filesearch/documents", tags=["FileSearch"])
async def filesearch_documents_proxy():
    url = f"{config.BRD_AGENT_API_BASE.rstrip('/')}/filesearch/documents"
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"filesearch documents proxy failed: {exc}")


class FileSearchIngestText(BaseModel):
    title: str
    content: str
    topic: Optional[str] = None
    source: Optional[str] = "meeting-master-ingest"


@app.post("/api/v1/filesearch/ingest-text", tags=["FileSearch"])
async def filesearch_ingest_text_proxy(req: FileSearchIngestText):
    url = f"{config.BRD_AGENT_API_BASE.rstrip('/')}/filesearch/ingest-text"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=req.dict())
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text[:500])
        return r.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"filesearch ingest-text proxy failed: {exc}")


class FileSearchQueryReq(BaseModel):
    query: str
    sessionId: Optional[str] = None


@app.post("/api/v1/filesearch/search", tags=["FileSearch"])
async def filesearch_search_proxy(req: FileSearchQueryReq):
    url = f"{config.BRD_AGENT_API_BASE.rstrip('/')}/filesearch/search"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=req.dict())
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text[:500])
        return r.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"filesearch search proxy failed: {exc}")


@app.post("/api/v1/filesearch/ingest-file", tags=["FileSearch"])
async def filesearch_ingest_file_proxy(file: UploadFile = File(...)):
    url = f"{config.BRD_AGENT_API_BASE.rstrip('/')}/filesearch/ingest-file"
    payload = await file.read()
    files = {"file": (file.filename or "upload.bin", payload, file.content_type or "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, files=files)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text[:500])
        return r.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"filesearch ingest-file proxy failed: {exc}")


# =============================================================================
# Static Files (Frontend)
# =============================================================================

# Mount frontend static files
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    # Mount static files for CSS, JS, etc.
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


@app.get("/", response_class=FileResponse, include_in_schema=False)
async def serve_frontend():
    """Serve the main frontend HTML"""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return FileResponse(frontend_path)
    return JSONResponse(
        status_code=404,
        content={"detail": "Frontend not found"}
    )


@app.get("/sw.js", include_in_schema=False)
async def serve_sw():
    """Service Worker must be served from root scope for PWA"""
    sw_path = Path(__file__).parent.parent / "frontend" / "sw.js"
    if sw_path.exists():
        return FileResponse(sw_path, media_type="application/javascript")
    return JSONResponse(status_code=404, content={"detail": "sw.js not found"})


@app.get("/manifest.json", include_in_schema=False)
async def serve_manifest():
    """PWA manifest must be at root"""
    manifest_path = Path(__file__).parent.parent / "frontend" / "manifest.json"
    if manifest_path.exists():
        return FileResponse(manifest_path, media_type="application/json")
    return JSONResponse(status_code=404, content={"detail": "manifest.json not found"})


# =============================================================================
# Run Application
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
