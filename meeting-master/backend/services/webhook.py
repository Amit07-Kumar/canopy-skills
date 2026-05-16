"""
n8n Webhook Integration Service

Provides async functions to call the 3 n8n webhook APIs used for the meeting
processing pipeline, following the same pattern as the brd-agent project:

  1. transcribe-audio   — Audio file → speaker-separated transcript
  2. AISummarization    — Speaker map → MOM + Tasks + Calendar events
  3. google_tool_event  — Recipients + data → Google Calendar + email MOM
  4. send-email         — User-triggered email delivery from the Email tab

Also includes an adapter function to map the simple webhook output into the
richer Meeting model used by meeting-master's local storage layer.
"""

import asyncio
import os
import re
import time
import uuid
import logging
import mimetypes
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from urllib.request import Request, urlopen

import httpx
from dateutil import parser as dateutil_parser

# Use relative imports when running as a package
try:
    from .. import config
except ImportError:
    import config

logger = logging.getLogger(__name__)

TRANSCRIBE_METADATA_KEYS = {"error", "code", "language_code", "request_id"}
SARVAM_BATCH_INIT_URL = "https://api.sarvam.ai/speech-to-text/job/v1"
SARVAM_BATCH_UPLOAD_URL = "https://api.sarvam.ai/speech-to-text/job/v1/upload-files"
SARVAM_BATCH_START_URL = "https://api.sarvam.ai/speech-to-text/job/v1/{job_id}/start"
SARVAM_BATCH_STATUS_URL = "https://api.sarvam.ai/speech-to-text/job/v1/{job_id}/status"
SARVAM_BATCH_DOWNLOAD_URL = "https://api.sarvam.ai/speech-to-text/job/v1/download-files"
SARVAM_BATCH_MODEL = os.getenv("SARVAM_BATCH_MODEL", "saaras:v3")
SARVAM_BATCH_MODE = os.getenv("SARVAM_BATCH_MODE", "transcribe")
SARVAM_BATCH_LANGUAGE = os.getenv("SARVAM_BATCH_LANGUAGE", "unknown")
SARVAM_BATCH_INITIAL_WAIT_SECONDS = max(1, int(os.getenv("SARVAM_BATCH_INITIAL_WAIT_SECONDS", "15")))
SARVAM_BATCH_POLL_INTERVAL_SECONDS = max(2, int(os.getenv("SARVAM_BATCH_POLL_INTERVAL_SECONDS", "10")))
SARVAM_BATCH_MAX_WAIT_SECONDS = max(60, int(os.getenv("SARVAM_BATCH_MAX_WAIT_SECONDS", "3600")))
SARVAM_BATCH_HTTP_ATTEMPTS = max(1, int(os.getenv("SARVAM_BATCH_HTTP_ATTEMPTS", "4")))
SARVAM_BATCH_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


async def _sarvam_request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    last_error: Optional[Exception] = None

    for attempt in range(1, SARVAM_BATCH_HTTP_ATTEMPTS + 1):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in SARVAM_BATCH_RETRYABLE_STATUS_CODES and attempt < SARVAM_BATCH_HTTP_ATTEMPTS:
                logger.warning(
                    "[Webhook] Sarvam %s %s returned %s on attempt %s/%s; retrying",
                    method,
                    url,
                    response.status_code,
                    attempt,
                    SARVAM_BATCH_HTTP_ATTEMPTS,
                )
                await asyncio.sleep(min(2 ** (attempt - 1), 5))
                continue

            response.raise_for_status()
            return response
        except httpx.RequestError as exc:
            last_error = exc
            if attempt >= SARVAM_BATCH_HTTP_ATTEMPTS:
                raise
            logger.warning(
                "[Webhook] Sarvam %s %s transport error on attempt %s/%s: %s. Retrying.",
                method,
                url,
                attempt,
                SARVAM_BATCH_HTTP_ATTEMPTS,
                exc,
            )
            await asyncio.sleep(min(2 ** (attempt - 1), 5))

    if last_error:
        raise last_error
    raise RuntimeError(f"Sarvam request failed unexpectedly for {method} {url}")


def _speaker_map_from_transcript_lines(transcript: str) -> Dict[str, str]:
    speaker_map: Dict[str, str] = {}
    line_pattern = re.compile(r"^\s*([^:]+):\s*(.*)$")

    for raw_line in str(transcript or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = line_pattern.match(line)
        if match:
            speaker = _normalize_speaker_label(match.group(1))
            text = match.group(2).strip()
        else:
            speaker = "Speaker 1"
            text = line

        if not text:
            continue
        speaker_map[speaker] = f"{speaker_map.get(speaker, '')} {text}".strip()

    return speaker_map


def _normalize_speaker_label(label: str) -> str:
    raw = str(label or "").strip().replace("_", " ")
    match = re.fullmatch(r"(?i)speaker\s*([0-9]+)", raw)
    if match:
        return f"Speaker {match.group(1)}"
    if raw.isdigit():
        return f"Speaker {int(raw) + 1}"
    return raw or "Speaker 1"


def _speaker_map_from_sarvam_payload(payload: Any) -> Dict[str, str]:
    if not isinstance(payload, dict):
        return {}

    speaker_map: Dict[str, str] = {}
    diarized = payload.get("diarized_transcript")
    entries = diarized.get("entries") if isinstance(diarized, dict) else None

    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            speaker = _normalize_speaker_label(
                entry.get("speaker_id") or entry.get("speaker") or entry.get("speaker_label")
            )
            text = str(entry.get("transcript") or entry.get("text") or "").strip()
            if not text:
                continue
            speaker_map[speaker] = f"{speaker_map.get(speaker, '')} {text}".strip()

    segments = payload.get("segments")
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            speaker = _normalize_speaker_label(
                segment.get("speaker") or segment.get("speaker_id") or segment.get("speaker_label")
            )
            text = str(segment.get("text") or segment.get("transcript") or "").strip()
            if not text:
                continue
            speaker_map[speaker] = f"{speaker_map.get(speaker, '')} {text}".strip()

    if speaker_map:
        return speaker_map

    transcript = str(payload.get("transcript") or "").strip()
    return _speaker_map_from_transcript_lines(transcript) if transcript else {}


def _speaker_map_from_transcribe_webhook_payload(payload: Any) -> Dict[str, str]:
    if isinstance(payload, list) and payload:
        return _speaker_map_from_transcribe_webhook_payload(payload[0])

    if not isinstance(payload, dict):
        return {}

    if payload.get("error"):
        return {}

    direct_speakers: Dict[str, str] = {}
    for key, value in payload.items():
        if key in TRANSCRIBE_METADATA_KEYS:
            continue
        text = str(value or "").strip()
        if not text:
            continue
        if re.fullmatch(r"(?i)speaker[_\s]*\d+", str(key or "").strip()) or str(key or "").strip().isdigit():
            direct_speakers[_normalize_speaker_label(str(key))] = text

    if direct_speakers:
        return direct_speakers

    results = payload.get("results")
    if isinstance(results, dict):
        nested = _speaker_map_from_sarvam_payload(results)
        if nested:
            return nested

    return _speaker_map_from_sarvam_payload(payload)


async def _transcribe_audio_via_n8n(audio_path: str) -> Dict[str, str]:
    if not config.N8N_WEBHOOK_TRANSCRIBE_AUDIO:
        return {}

    content_type = mimetypes.guess_type(audio_path)[0] or "audio/webm"
    filename = os.path.basename(audio_path)

    with open(audio_path, "rb") as file_handle:
        file_bytes = file_handle.read()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.post(
            config.N8N_WEBHOOK_TRANSCRIBE_AUDIO,
            headers={
                "X-Language": SARVAM_BATCH_LANGUAGE,
                "X-Model": SARVAM_BATCH_MODEL,
                "X-Timestamps": "true",
            },
            files={"audio": (filename, file_bytes, content_type)},
            timeout=float(config.N8N_WEBHOOK_TIMEOUT),
        )

    if response.status_code != 200:
        logger.warning(
            "[Webhook] transcription webhook returned %s: %s",
            response.status_code,
            response.text[:500],
        )
        return {}

    try:
        payload = response.json()
    except ValueError:
        logger.warning("[Webhook] transcription webhook returned non-JSON payload")
        return {}

    speaker_map = _speaker_map_from_transcribe_webhook_payload(payload)
    if not speaker_map:
        logger.warning("[Webhook] transcription webhook returned no speaker transcript")
    return speaker_map


def _extract_sarvam_output_files(status_payload: dict) -> list[str]:
    file_names: list[str] = []
    for detail in status_payload.get("job_details") or []:
        if not isinstance(detail, dict):
            continue
        for output in detail.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            file_name = str(output.get("file_name") or "").strip()
            if file_name:
                file_names.append(file_name)
    return file_names


async def _download_sarvam_output_payloads(
    client: httpx.AsyncClient,
    headers: dict,
    job_id: str,
    file_names: list[str],
) -> list[dict]:
    if not file_names:
        return []

    download_response = await client.post(
        SARVAM_BATCH_DOWNLOAD_URL,
        headers={**headers, "Content-Type": "application/json"},
        json={"job_id": job_id, "files": file_names},
        timeout=30.0,
    )
    download_response.raise_for_status()
    download_payload = download_response.json()
    download_urls = download_payload.get("download_urls") or {}
    if not isinstance(download_urls, dict):
        return []

    payloads: list[dict] = []
    for file_name in file_names:
        details = download_urls.get(file_name) or {}
        if not isinstance(details, dict):
            continue
        file_url = details.get("file_url")
        if not file_url:
            continue
        try:
            payload = await asyncio.to_thread(_read_json_from_signed_url, file_url)
        except ValueError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)

    return payloads


def _upload_bytes_to_signed_url(url: str, content: bytes, content_type: str) -> None:
    request = Request(
        url,
        data=content,
        method="PUT",
        headers={
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": content_type or "application/octet-stream",
        },
    )
    with urlopen(request, timeout=600) as response:
        status = getattr(response, "status", None) or response.getcode()
        if status not in {200, 201}:
            raise RuntimeError(f"Signed upload failed with HTTP {status}")


def _read_json_from_signed_url(url: str) -> dict:
    request = Request(url, method="GET")
    with urlopen(request, timeout=60) as response:
        return httpx.Response(200, content=response.read()).json()


async def _transcribe_audio_with_sarvam_batch_bytes(
    filename: str,
    file_bytes: bytes,
    content_type: str,
) -> Dict[str, str]:
    if not config.SARVAM_API_KEY:
        raise RuntimeError("SARVAM_API_KEY is not configured")

    headers = {"api-subscription-key": config.SARVAM_API_KEY}
    job_filename = os.path.basename(filename or f"meeting-{uuid.uuid4().hex}.mp3")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        init_response = await _sarvam_request_with_retry(
            client,
            "POST",
            SARVAM_BATCH_INIT_URL,
            headers={**headers, "Content-Type": "application/json"},
            json={
                "job_parameters": {
                    "model": SARVAM_BATCH_MODEL,
                    "mode": SARVAM_BATCH_MODE,
                    "language_code": SARVAM_BATCH_LANGUAGE,
                    "with_diarization": True,
                    "with_timestamps": True,
                }
            },
            timeout=30.0,
        )
        init_payload = init_response.json()

        job_id = str(init_payload.get("job_id") or "").strip()
        if not job_id:
            raise RuntimeError("Sarvam batch init response is missing job_id")

        upload_links_response = await _sarvam_request_with_retry(
            client,
            "POST",
            SARVAM_BATCH_UPLOAD_URL,
            headers={**headers, "Content-Type": "application/json"},
            json={"job_id": job_id, "files": [job_filename]},
            timeout=30.0,
        )
        upload_links_payload = upload_links_response.json()
        upload_urls = upload_links_payload.get("upload_urls") or {}
        upload_details = upload_urls.get(job_filename) if isinstance(upload_urls, dict) else None
        upload_url = upload_details.get("file_url") if isinstance(upload_details, dict) else None
        if not upload_url:
            raise RuntimeError("Sarvam batch upload URL was not returned for the audio file")

        await asyncio.to_thread(_upload_bytes_to_signed_url, upload_url, file_bytes, content_type)

        await _sarvam_request_with_retry(
            client,
            "POST",
            SARVAM_BATCH_START_URL.format(job_id=job_id),
            headers={**headers, "Content-Type": "application/json"},
            json={},
            timeout=30.0,
        )

        await asyncio.sleep(SARVAM_BATCH_INITIAL_WAIT_SECONDS)
        deadline = time.monotonic() + SARVAM_BATCH_MAX_WAIT_SECONDS

        while True:
            status_response = await _sarvam_request_with_retry(
                client,
                "GET",
                SARVAM_BATCH_STATUS_URL.format(job_id=job_id),
                headers=headers,
                timeout=30.0,
            )
            status_payload = status_response.json()

            state = str(status_payload.get("job_state") or status_payload.get("status") or "").strip().lower()
            if state == "completed":
                speaker_map = _speaker_map_from_sarvam_payload(status_payload)
                if speaker_map:
                    return speaker_map

                output_payloads = await _download_sarvam_output_payloads(
                    client,
                    headers,
                    job_id,
                    _extract_sarvam_output_files(status_payload),
                )
                for output_payload in output_payloads:
                    speaker_map = _speaker_map_from_sarvam_payload(output_payload)
                    if speaker_map:
                        return speaker_map

                raise RuntimeError("Sarvam batch completed but returned no speaker transcript")

            if state in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError(str(status_payload.get("error") or status_payload))

            if time.monotonic() >= deadline:
                raise TimeoutError(f"Sarvam batch transcription timed out after {SARVAM_BATCH_MAX_WAIT_SECONDS} seconds")

            await asyncio.sleep(SARVAM_BATCH_POLL_INTERVAL_SECONDS)


# =============================================================================
# Webhook Client Functions
# =============================================================================

async def transcribe_audio_webhook(audio_path: str) -> Dict[str, str]:
    """
    Send audio file to the configured transcription n8n webhook.

    Args:
        audio_path: Path to the audio file on disk (e.g. /app/uploads/uuid.webm)

    Returns:
        Speaker map dict like {"Speaker 1": "Hello ...", "Speaker 2": "Sure ..."}
        Empty dict on failure.
    """
    logger.info(f"[Webhook] Transcribing audio via configured webhook pipeline: {audio_path}")
    try:
        speaker_map = await _transcribe_audio_via_n8n(audio_path)
        if speaker_map:
            logger.info(
                f"[Webhook] n8n transcription complete — {len(speaker_map)} speakers detected"
            )
            return speaker_map

        logger.warning("[Webhook] n8n transcription returned no result; falling back to direct Sarvam batch")

        # Detect MIME type from file extension
        content_type = mimetypes.guess_type(audio_path)[0] or "audio/webm"
        filename = os.path.basename(audio_path)

        with open(audio_path, "rb") as f:
            file_bytes = f.read()

        speaker_map = await _transcribe_audio_with_sarvam_batch_bytes(filename, file_bytes, content_type)
        logger.info(
            f"[Webhook] Sarvam batch transcription complete — {len(speaker_map)} speakers detected"
        )
        return speaker_map

    except Exception as e:
        logger.error(f"[Webhook] transcription webhook failed: {e}")
        return {}


async def summarize_transcript_webhook(speaker_map: Dict[str, str]) -> Dict[str, Any]:
    """
    Send speaker-separated transcript to the AISummarization n8n webhook.

    Args:
        speaker_map: Dict keyed by speaker label, e.g.
                     {"Speaker 1": "text...", "Speaker 2": "text..."}

    Returns:
        Dict with keys "MOM", "Task", "calender" (note: n8n uses this spelling).
        Empty dict on failure.
    """
    logger.info(f"[Webhook] Summarizing transcript via n8n ({len(speaker_map)} speakers)")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                config.N8N_WEBHOOK_AI_SUMMARIZATION,
                json=speaker_map,
                timeout=60.0,
            )

        if response.status_code != 200:
            logger.error(
                f"[Webhook] AISummarization returned {response.status_code}: "
                f"{response.text[:500]}"
            )
            return {}

        # Response format: [{"MOM": [...], "Task": [...], "calender": [...]}]
        data = response.json()
        result = data[0] if isinstance(data, list) and len(data) > 0 else data
        logger.info(
            f"[Webhook] Summarization complete — "
            f"MOM: {len(result.get('MOM', []))}, "
            f"Tasks: {len(result.get('Task', []))}, "
            f"Calendar: {len(result.get('calender', []))}"
        )
        return result

    except Exception as e:
        logger.error(f"[Webhook] AISummarization failed: {e}")
        return {}


async def trigger_google_tools_webhook(
    recipients: List[str],
    calendar: List[Dict],
    tasks: List[Any],
    mom: List[Any],
) -> Dict[str, Any]:
    """
    Trigger Google Workspace integrations: schedule Calendar events,
    log tasks, and email MOM to all recipients.

    Args:
        recipients: List of email addresses to receive MOM
        calendar:   List of calendar event dicts [{"title": "...", "time": "..."}]
        tasks:      List of task items for the webhook payload
        mom:        List of MOM items for the webhook payload

    Returns:
        {"success": True/False, "message": "..."} dict.
    """
    if not recipients:
        logger.warning("[Webhook] google_tool_event skipped — no recipients provided")
        return {"success": False, "message": "No recipients provided"}

    logger.info(
        f"[Webhook] Triggering Google Tools for {len(recipients)} recipients"
    )
    try:
        payload = {
            "recipients": recipients,
            "calender": calendar,  # n8n uses this spelling
            "Task": tasks,
            "MOM": mom,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                config.N8N_WEBHOOK_GOOGLE_TOOLS,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=60.0,
            )

        if response.status_code != 200:
            error_msg = (
                f"Google Tools returned {response.status_code}: "
                f"{response.text[:500]}"
            )
            logger.error(f"[Webhook] {error_msg}")
            return {"success": False, "message": error_msg}

        data = response.json()
        msg = data.get("message", "Events logged and emails sent successfully.")
        logger.info(f"[Webhook] Google Tools success: {msg}")
        return {"success": True, "message": msg}

    except Exception as e:
        logger.error(f"[Webhook] google_tool_event failed: {e}")
        return {"success": False, "message": str(e)}


async def trigger_email_send_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trigger the user-configured email delivery webhook when the user clicks
    the Send Email button in the UI.

    Args:
        payload: Minimal JSON body expected by google_tool_event, typically
                 containing recipients, calender, Task, and MOM keys.

    Returns:
        Dict with success/message plus echoed request metadata and parsed
        webhook response when available.
    """
    if not config.N8N_WEBHOOK_SEND_EMAIL:
        return {"success": False, "message": "Send email webhook is not configured"}

    logger.info("[Webhook] Triggering send-email workflow webhook")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                config.N8N_WEBHOOK_SEND_EMAIL,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=float(config.N8N_WEBHOOK_TIMEOUT),
            )

        response_payload: Any
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = response.text

        if response.status_code < 200 or response.status_code >= 300:
            error_msg = (
                f"Send email webhook returned {response.status_code}: "
                f"{str(response_payload)[:500]}"
            )
            logger.error(f"[Webhook] {error_msg}")
            return {
                "success": False,
                "message": error_msg,
                "status_code": response.status_code,
                "response": response_payload,
            }

        logger.info("[Webhook] Send email workflow completed successfully")
        return {
            "success": True,
            "message": "Email workflow triggered successfully",
            "status_code": response.status_code,
            "response": response_payload,
        }

    except Exception as e:
        logger.error(f"[Webhook] send-email failed: {e}")
        return {"success": False, "message": str(e)}


# =============================================================================
# Data Mapping Adapter
# =============================================================================

_YYYY_MM_DD_RE = None  # lazy-compiled below


def _fix_past_year(date_str: Any, reference_date: datetime) -> str:
    """
    Workaround for the AISummarization LLM hallucinating prior-year dates
    (e.g. 2023-10-26 today, 2026-05-14). If the leading YYYY-MM-DD is in the
    past relative to `reference_date`, bump it to the current/next year.

    Pure string transform: only touches the first ISO-date substring.
    """
    global _YYYY_MM_DD_RE
    if not date_str:
        return ""
    text = str(date_str)
    import re
    if _YYYY_MM_DD_RE is None:
        _YYYY_MM_DD_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    match = _YYYY_MM_DD_RE.search(text)
    if not match:
        return text
    yr, mo, da = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if yr >= reference_date.year:
        return text
    try:
        replacement_year = reference_date.year
        candidate = datetime(replacement_year, mo, da)
        # If month/day already passed this year, push to next year.
        if candidate.date() < reference_date.date():
            candidate = datetime(replacement_year + 1, mo, da)
        new_iso = candidate.strftime("%Y-%m-%d")
        return text[: match.start()] + new_iso + text[match.end():]
    except ValueError:
        return text


def _parse_natural_time(time_str: str, reference_date: datetime) -> Optional[datetime]:
    """
    Best-effort parsing of natural language time strings like
    "Tomorrow at 10 AM", "Friday 2 PM", "Next Monday 3:00 PM".

    Falls back to None if unparseable.
    """
    if not time_str:
        return None

    try:
        # dateutil handles many natural formats when given a reference date
        return dateutil_parser.parse(time_str, default=reference_date, fuzzy=True)
    except (ValueError, OverflowError):
        pass

    # Manual fallback for common patterns
    lower = time_str.lower()
    try:
        if "tomorrow" in lower:
            base = reference_date + timedelta(days=1)
            # Try to extract time portion after "tomorrow"
            time_part = lower.replace("tomorrow", "").strip().lstrip("at").strip()
            if time_part:
                parsed_time = dateutil_parser.parse(time_part, default=base, fuzzy=True)
                return parsed_time
            return base.replace(hour=10, minute=0, second=0)
    except (ValueError, OverflowError):
        pass

    return None


def map_webhook_to_meeting_updates(
    speaker_map: Dict[str, str],
    summary_data: Dict[str, Any],
    meeting_date: datetime,
    title: str = "Meeting",
) -> Dict[str, Any]:
    """
    Maps the simple webhook output into the rich field structure expected by
    meeting-master's stored meeting document.

    Args:
        speaker_map:  {"Speaker 1": "text...", ...} from transcribe-audio
        summary_data: {"MOM": [...], "Task": [...], "calender": [...]} from AISummarization
        meeting_date: Reference date for relative time parsing
        title:        Meeting title for email subject

    Returns:
        Dict of fields ready to pass to es.update_meeting()
    """
    raw_mom = summary_data.get("MOM", [])
    raw_tasks = summary_data.get("Task", [])
    calendar_items = summary_data.get("calender", [])

    # Normalize: n8n may return MOM/Task items as dicts or plain strings.
    # MOM dicts use keys: topic, discussion_summary, decisions, owner
    # Task dicts use keys: task_title, description, category, priority, edd
    def _normalize_mom_item(item) -> str:
        if isinstance(item, str):
            # Guard: if it looks like Python repr of a dict, try to parse it
            stripped = item.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    import ast
                    parsed = ast.literal_eval(stripped)
                    if isinstance(parsed, dict):
                        return _normalize_mom_item(parsed)
                except Exception:
                    pass
            return item
        if isinstance(item, dict):
            topic = item.get("topic", "")
            summary = item.get("discussion_summary", "") or item.get("summary", "")
            decision = item.get("decisions", "") or item.get("decision", "")
            owner = item.get("owner", "")
            parts = []
            if topic:
                parts.append(f"**{topic}**")
            if summary:
                parts.append(summary)
            if decision:
                parts.append(f"Decision: {decision}")
            if owner:
                parts.append(f"Owner: {owner}")
            return " - ".join(parts) if parts else str(item)
        return str(item)

    def _normalize_task_item(item):
        """Return a (title, description, priority, due_date) tuple from any task format."""
        if isinstance(item, str):
            return item, None, "MEDIUM", None
        if isinstance(item, dict):
            title = (
                item.get("task_title")
                or item.get("title")
                or item.get("text")
                or item.get("content")
                or "Untitled Task"
            )
            description = item.get("description") or item.get("desc") or None
            raw_priority = str(item.get("priority") or "Medium").upper()
            priority = raw_priority if raw_priority in ("HIGH", "MEDIUM", "LOW", "CRITICAL") else "MEDIUM"
            raw_due = item.get("edd") or item.get("due_date") or item.get("deadline") or None
            # Only keep due_date if it looks like ISO (YYYY-MM-DD); discard natural language.
            # If LLM hallucinated a prior-year date, bump it to the current/next year.
            due_date = None
            if raw_due:
                import re as _re
                if _re.match(r'^\d{4}-\d{2}-\d{2}', str(raw_due)):
                    due_date = _fix_past_year(str(raw_due)[:10], meeting_date)
            return title, description, priority, due_date
        return str(item), None, "MEDIUM", None

    mom_items = [_normalize_mom_item(item) for item in raw_mom]

    # --- Build raw transcript from speaker map ---
    raw_transcript = "\n".join(
        f"[{speaker}]: {text}" for speaker, text in speaker_map.items()
    )

    # --- Map tasks: properly extract title, description, priority, due_date ---
    # AISummarization workflow's AI Scrum Assistant emits one of these six
    # categories: Development, Research, Infra, Bug, Ops, Documentation.
    # Keep those as-is (uppercased to match our internal enum naming) plus
    # the legacy aliases we already accepted. Anything unknown falls to OPS.
    _CATEGORY_MAP = {
        "BUG": "BUG", "BUGFIX": "BUG", "BUG_FIX": "BUG", "FIX": "BUG", "DEFECT": "BUG",
        "FEATURE": "FEATURE", "FEATURE_REQUEST": "FEATURE", "ENHANCEMENT": "FEATURE",
        "DEVELOPMENT": "DEVELOPMENT", "DEV": "DEVELOPMENT", "ENG": "DEVELOPMENT", "ENGINEERING": "DEVELOPMENT",
        "RESEARCH": "RESEARCH", "ANALYSIS": "RESEARCH", "DISCOVERY": "RESEARCH",
        "INFRA": "INFRA", "INFRASTRUCTURE": "INFRA", "DEVOPS": "INFRA", "DEPLOY": "INFRA",
        "OPS": "OPS", "OPERATIONS": "OPS", "OPERATIONAL": "OPS", "OTHER": "OPS",
        "MISC": "OPS", "GENERAL": "OPS",
        "DOCUMENTATION": "DOCUMENTATION", "DOCS": "DOCUMENTATION", "DOC": "DOCUMENTATION",
        "MEETING": "MEETING", "CALL": "MEETING", "SYNC": "MEETING",
    }

    def _safe_category(raw_cat: str) -> str:
        """Map any n8n category string to a stored category. Defaults to OPS
        so the meeting record never shows the meaningless 'OTHER' tag."""
        normalized = str(raw_cat or "OPS").upper().replace(" ", "_").replace("-", "_")
        return _CATEGORY_MAP.get(normalized, "OPS")

    tasks = []
    for i, raw_task in enumerate(raw_tasks, start=1):
        task_title, task_desc, task_priority, task_due = _normalize_task_item(raw_task)
        raw_cat = raw_task.get("category", "OTHER") if isinstance(raw_task, dict) else "OTHER"
        tasks.append({
            "id": f"TASK_{i:03d}",
            "title": task_title,
            "description": task_desc,
            "assignee": None,
            "priority": task_priority,
            "category": _safe_category(raw_cat),
            "status": "TODO",
            "due_date": task_due,
            "deadline_source": "n8n webhook" if task_due else "not specified",
            "dependencies": [],
            "context": "Extracted from meeting via n8n webhook",
        })

    # --- Map calendar events ---
    # Stage 2 may return either:
    #   {"event_title": "...", "event_date": "YYYY-MM-DD", "event_type": "...", "notes": "...", "participants": [...]}
    # or the older simpler:
    #   {"title": "...", "time": "..."}
    calendar_events = []
    for i, event in enumerate(calendar_items, start=1):
        if isinstance(event, dict):
            event_title = (
                event.get("event_title")
                or event.get("title")
                or event.get("subject")
                or f"Event {i}"
            )
            time_str = (
                event.get("event_date")
                or event.get("time")
                or event.get("start_time")
                or event.get("date")
                or ""
            )
            raw_type = str(event.get("event_type") or event.get("type") or "MEETING").upper()
            # CalendarEventType enum allows only MEETING / REMINDER / DEADLINE.
            # Map any descriptive n8n category to the closest valid value.
            _TYPE_MAP = {
                "MEETING": "MEETING", "CALL": "MEETING", "SYNC": "MEETING", "DEMO": "MEETING",
                "DISCUSSION": "MEETING", "STANDUP": "MEETING",
                "REVIEW": "REMINDER", "FOLLOWUP": "REMINDER", "FOLLOW_UP": "REMINDER",
                "REMINDER": "REMINDER",
                "DEADLINE": "DEADLINE", "DUE": "DEADLINE", "EDD": "DEADLINE",
            }
            event_type = _TYPE_MAP.get(raw_type, "MEETING")
            notes = event.get("notes") or event.get("description")
        else:
            event_title = str(event)
            time_str = ""
            event_type = "MEETING"
            notes = None

        # Normalize hallucinated past-year dates from the LLM (see post-process below).
        time_str = _fix_past_year(time_str, meeting_date)
        start_dt = _parse_natural_time(time_str, meeting_date)
        if start_dt:
            # If the parsed datetime is before meeting_date, force-bump year(s) forward.
            while start_dt < meeting_date:
                try:
                    start_dt = start_dt.replace(year=start_dt.year + 1)
                except ValueError:
                    break
            end_dt = start_dt + timedelta(hours=1)
        else:
            start_dt = meeting_date + timedelta(days=1, hours=10)
            end_dt = start_dt + timedelta(hours=1)

        description_parts = []
        if time_str:
            description_parts.append(f"Time mentioned: {time_str}")
        if notes:
            description_parts.append(str(notes))

        calendar_events.append({
            "id": f"CAL_{i:03d}",
            "title": event_title,
            "description": " — ".join(description_parts) if description_parts else None,
            "start_datetime": start_dt.isoformat(),
            "end_datetime": end_dt.isoformat(),
            "attendees": [],
            "source": f"n8n webhook — '{time_str}'" if time_str else "n8n webhook",
            "type": event_type,
            "google_event_id": None,
        })

    # --- Build rich Markdown mail body ---
    def _format_mail_body(title: str, date: datetime, raw_mom_items: list, task_list: list) -> str:
        lines = [
            f"# Minutes of Meeting: {title}",
            f"**Date:** {date.strftime('%B %d, %Y')}",
            "",
            "---",
            "",
            "## Discussion Points",
            "",
        ]
        for item in raw_mom_items:
            if isinstance(item, dict):
                topic = item.get("topic", "")
                summary = item.get("discussion_summary", "") or item.get("summary", "")
                decision = item.get("decisions", "") or item.get("decision", "")
                owner = item.get("owner", "")
                if topic:
                    lines.append(f"### {topic}")
                if summary:
                    lines.append(summary)
                if decision:
                    lines.append(f"**Decision:** {decision}")
                if owner:
                    lines.append(f"**Owner:** {owner}")
                lines.append("")
            else:
                lines.append(f"- {item}")
        if task_list:
            lines += ["---", "", "## Action Items", ""]
            for i, t in enumerate(task_list, 1):
                if isinstance(t, dict):
                    t_title = t.get("task_title") or t.get("title") or "Task"
                    t_owner = t.get("owner") or t.get("assignee") or ""
                    t_due = t.get("edd") or t.get("due_date") or ""
                    if t_due:
                        t_due = _fix_past_year(t_due, date)
                    row = f"{i}. **{t_title}**"
                    if t_owner:
                        row += f" — {t_owner}"
                    if t_due:
                        row += f" (by {t_due})"
                    lines.append(row)
                else:
                    lines.append(f"{i}. {t}")
        return "\n".join(lines)

    mail_body = _format_mail_body(title, meeting_date, raw_mom, raw_tasks)
    mail = {
        "subject": f"MoM: {title} - {meeting_date.strftime('%Y-%m-%d')}",
        "to": [],
        "cc": [],
        "body": mail_body,
        "sent": False,
        "sent_at": None,
    }

    # --- Summary from MOM topics ---
    def _mom_topic(item) -> str:
        if isinstance(item, dict):
            return item.get("topic") or item.get("discussion_summary", "")[:60] or "Discussion"
        return str(item)[:80]

    summary = "; ".join(_mom_topic(item) for item in raw_mom[:3]) if raw_mom else "No summary available."

    return {
        "raw_transcript": raw_transcript,
        "transcript_en": raw_transcript,  # Webhook gives us one language only
        "transcript_hi": None,
        "transcript_hinglish": None,
        "attendees": [
            {
                "speaker_id": speaker_key.replace(" ", "_").upper(),
                "name": speaker_key,
                "email": None,
                "identified": False,
                "hint": "Identified by n8n transcription",
            }
            for speaker_key in speaker_map.keys()
        ],
        "tasks": tasks,
        "calendar_events": calendar_events,
        "mail": mail,
        "summary": summary,
        "tags": [],
        "sentiment": None,
        "confidence": None,
    }
