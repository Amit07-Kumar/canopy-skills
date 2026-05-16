"""KPI helpers for meeting execution intelligence."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


COMMITMENT_PATTERN = re.compile(
    r"\b(will|should|need to|needs to|must|follow up|schedule|send|prepare|deploy|fix|share|review|call|draft|create|update)\b",
    re.IGNORECASE,
)


def _to_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _safe_percent(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _detect_commitments(text: str) -> int:
    if not text:
        return 0
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    actionable = []
    seen = set()
    for sentence in sentences:
        normalized = re.sub(r"\s+", " ", str(sentence or "").strip().lower())
        if not normalized or not COMMITMENT_PATTERN.search(normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        actionable.append(normalized)
    return len(actionable)


def _build_commitment_text(meeting: Dict[str, Any], mail: Dict[str, Any]) -> str:
    parts = [
        str(meeting.get("raw_transcript") or ""),
        str(meeting.get("transcript_en") or ""),
        str(meeting.get("summary") or ""),
    ]
    unique_parts = []
    seen = set()
    for part in parts:
        normalized = re.sub(r"\s+", " ", part.strip())
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_parts.append(normalized)
    return "\n".join(unique_parts)


def _action_speed_score(time_to_action_seconds: Optional[float], email_ready: bool, calendar_ready: bool) -> float:
    if time_to_action_seconds is not None:
        minutes = time_to_action_seconds / 60
        if minutes <= 5:
            return 100.0
        if minutes <= 30:
            return 90.0
        if minutes <= 120:
            return 75.0
        if minutes <= 1440:
            return 60.0
        return 40.0
    if email_ready or calendar_ready:
        return 55.0
    return 0.0


def compute_meeting_kpis(meeting: Dict[str, Any]) -> Dict[str, Any]:
    tasks = [task for task in (meeting.get("tasks") or []) if isinstance(task, dict)]
    calendar_events = [event for event in (meeting.get("calendar_events") or []) if isinstance(event, dict)]
    mail = meeting.get("mail") or {}
    automation = meeting.get("automation") or {}

    transcript_text = _build_commitment_text(meeting, mail)

    task_count = len(tasks)
    detected_commitments = max(_detect_commitments(transcript_text), task_count)
    assignee_count = sum(1 for task in tasks if str(task.get("assignee") or "").strip())
    due_date_count = sum(1 for task in tasks if task.get("due_date") or str(task.get("deadline_source") or "").strip() not in {"", "not specified"})
    priority_count = sum(1 for task in tasks if str(task.get("priority") or "").strip())
    context_count = sum(1 for task in tasks if str(task.get("description") or task.get("context") or "").strip())
    closed_count = sum(1 for task in tasks if str(task.get("status") or "").upper() in {"DONE", "COMPLETED", "CLOSED"})

    recipient_count = len([recipient for recipient in (automation.get("recipients") or mail.get("to") or []) if str(recipient).strip()])
    email_ready = bool(str(mail.get("subject") or "").strip() and str(mail.get("body") or "").strip() and recipient_count)
    calendar_ready = bool(calendar_events and recipient_count)

    ownership_coverage = _safe_percent(assignee_count, task_count)
    due_date_coverage = _safe_percent(due_date_count, task_count)
    priority_clarity_rate = _safe_percent(priority_count, task_count)
    task_context_coverage = _safe_percent(context_count, task_count)
    closure_rate = _safe_percent(closed_count, task_count)
    calendar_coverage = min(100.0, round((len(calendar_events) / max(task_count, 1)) * 100, 1)) if task_count else (100.0 if calendar_events else 0.0)
    action_leakage_rate = round(max(detected_commitments - task_count, 0) / detected_commitments * 100, 1) if detected_commitments else 0.0

    context_completeness_score = round(
        (15.0 if str(meeting.get("title") or "").strip() else 0.0)
        + (20.0 if str(meeting.get("summary") or "").strip() else 0.0)
        + (15.0 if str(mail.get("body") or "").strip() else 0.0)
        + (20.0 * (ownership_coverage / 100.0))
        + (15.0 * (due_date_coverage / 100.0))
        + (5.0 * (priority_clarity_rate / 100.0))
        + (5.0 * (task_context_coverage / 100.0))
        + (5.0 * (calendar_coverage / 100.0))
        ,
        1,
    )

    baseline_ts = _to_datetime(automation.get("baseline_timestamp")) or _to_datetime(meeting.get("processed_at")) or _to_datetime(meeting.get("created_at"))
    action_ts = _to_datetime(automation.get("dispatched_at")) or _to_datetime(mail.get("sent_at"))
    time_to_action_seconds = round((action_ts - baseline_ts).total_seconds(), 1) if action_ts and baseline_ts else None
    action_speed_score = _action_speed_score(time_to_action_seconds, email_ready=email_ready, calendar_ready=calendar_ready)

    execution_health_index = round(
        (0.35 * context_completeness_score)
        + (0.25 * (100.0 - action_leakage_rate))
        + (0.20 * closure_rate)
        + (0.20 * action_speed_score),
        1,
    )

    missing_fields: List[str] = []
    if not meeting.get("summary"):
        missing_fields.append("summary")
    if task_count and ownership_coverage < 100:
        missing_fields.append("task_owner")
    if task_count and due_date_coverage < 100:
        missing_fields.append("due_date")
    if task_count and priority_clarity_rate < 100:
        missing_fields.append("priority")
    if not recipient_count:
        missing_fields.append("recipient_email")
    if task_count and not calendar_events:
        missing_fields.append("calendar_follow_up")

    return {
        "execution_health_index": execution_health_index,
        "context_completeness_score": context_completeness_score,
        "action_leakage_rate": action_leakage_rate,
        "closure_rate": closure_rate,
        "time_to_action_seconds": time_to_action_seconds,
        "ownership_coverage": ownership_coverage,
        "due_date_coverage": due_date_coverage,
        "priority_clarity_rate": priority_clarity_rate,
        "calendar_coverage": calendar_coverage,
        "task_context_coverage": task_context_coverage,
        "detected_commitments": detected_commitments,
        "task_count": task_count,
        "calendar_count": len(calendar_events),
        "recipient_count": recipient_count,
        "email_ready": email_ready,
        "auto_dispatch_success": bool(automation.get("dispatch_success")),
        "missing_fields": missing_fields,
        "generated_at": datetime.utcnow().isoformat(),
    }


def compute_portfolio_kpis(meetings: List[Dict[str, Any]]) -> Dict[str, Any]:
    scoped = [meeting for meeting in meetings if isinstance(meeting, dict)]
    processed = [meeting for meeting in scoped if str(meeting.get("status") or "").lower() == "completed"]
    kpis = [meeting.get("kpis") or compute_meeting_kpis(meeting) for meeting in processed]

    def average(key: str) -> float:
        values = [float(item.get(key) or 0.0) for item in kpis]
        return round(sum(values) / len(values), 1) if values else 0.0

    total_tasks = sum(int(item.get("task_count") or 0) for item in kpis)
    closed_tasks = sum(
        sum(1 for task in (meeting.get("tasks") or []) if str(task.get("status") or "").upper() in {"DONE", "COMPLETED", "CLOSED"})
        for meeting in processed
    )
    auto_dispatched = sum(1 for item in kpis if item.get("auto_dispatch_success"))
    time_values = [float(item.get("time_to_action_seconds")) for item in kpis if item.get("time_to_action_seconds") is not None]
    high_risk = sum(1 for item in kpis if float(item.get("execution_health_index") or 0.0) < 60.0)

    return {
        "total_meetings": len(scoped),
        "processed_meetings": len(processed),
        "execution_health_index": average("execution_health_index"),
        "context_completeness_score": average("context_completeness_score"),
        "action_leakage_rate": average("action_leakage_rate"),
        "closure_rate": round((closed_tasks / total_tasks) * 100, 1) if total_tasks else 0.0,
        "time_to_action_seconds": round(sum(time_values) / len(time_values), 1) if time_values else None,
        "automation_coverage": round((auto_dispatched / len(kpis)) * 100, 1) if kpis else 0.0,
        "high_risk_meetings": high_risk,
    }