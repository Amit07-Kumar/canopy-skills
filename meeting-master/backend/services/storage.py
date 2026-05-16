"""
Meeting Master - Local JSON Storage Service

Stores users and meetings in a single JSON file so the app can run without
external database dependencies.
"""

import json
import logging
import os
from copy import deepcopy
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

# Use relative imports when running as a package
try:
    from ..config import STORAGE_FILE_PATH
except ImportError:
    from config import STORAGE_FILE_PATH

logger = logging.getLogger(__name__)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return value


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.min
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min


class LocalStorageService:
    """Simple JSON-file persistence for users and meetings."""

    def __init__(self, storage_file: str = None):
        self.storage_file = Path(storage_file or STORAGE_FILE_PATH)
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._ensure_store()

    def _default_store(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        return {"users": {}, "meetings": {}}

    def _ensure_store(self) -> None:
        with self._lock:
            if self.storage_file.exists():
                return
            self._write_store(self._default_store())

    def _read_store(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        if not self.storage_file.exists():
            return self._default_store()

        try:
            with self.storage_file.open("r", encoding="utf-8") as handle:
                raw = handle.read().strip()
                if not raw:
                    return self._default_store()
                data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read storage file %s: %s", self.storage_file, exc)
            return self._default_store()

        data.setdefault("users", {})
        data.setdefault("meetings", {})
        return data

    def _write_store(self, data: Dict[str, Any]) -> None:
        normalized = _normalize_value(data)
        tmp_path = self.storage_file.with_suffix(self.storage_file.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=2, sort_keys=True)
        os.replace(tmp_path, self.storage_file)

    def _match_search(self, meeting: Dict[str, Any], query: str) -> bool:
        if not query:
            return True

        haystack = [
            meeting.get("title", ""),
            meeting.get("raw_transcript", ""),
            meeting.get("transcript_en", ""),
            meeting.get("transcript_hi", ""),
            meeting.get("transcript_hinglish", ""),
            meeting.get("summary", ""),
            " ".join(str(tag) for tag in meeting.get("tags", [])),
        ]

        for task in meeting.get("tasks", []):
            if isinstance(task, dict):
                haystack.append(task.get("title", ""))
                haystack.append(task.get("description", ""))

        combined = " ".join(part for part in haystack if part).lower()
        return query.lower() in combined

    def health(self) -> Dict[str, Any]:
        with self._lock:
            store = self._read_store()
            return {
                "status": "OK",
                "backend": "json_file",
                "storage_file": str(self.storage_file),
                "user_count": len(store["users"]),
                "meeting_count": len(store["meetings"]),
            }

    # =========================================================================
    # User Operations
    # =========================================================================

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            user = self._read_store()["users"].get(user_id)
            return deepcopy(user) if user else None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        email = (email or "").lower()
        with self._lock:
            for user in self._read_store()["users"].values():
                if str(user.get("email", "")).lower() == email:
                    return deepcopy(user)
        return None

    def get_user_by_google_id(self, google_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for user in self._read_store()["users"].values():
                if user.get("google_id") == google_id:
                    return deepcopy(user)
        return None

    def create_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = _normalize_value(user_data)
        user_id = normalized["user_id"]

        with self._lock:
            store = self._read_store()
            existing = store["users"].get(user_id, {})
            merged = deepcopy(existing)
            merged.update(normalized)

            if existing.get("settings") and not normalized.get("settings"):
                merged["settings"] = existing["settings"]
            else:
                merged.setdefault("settings", {})

            if existing.get("team_members") and not normalized.get("team_members"):
                merged["team_members"] = existing["team_members"]
            else:
                merged.setdefault("team_members", [])

            if existing.get("created_at") and not normalized.get("created_at"):
                merged["created_at"] = existing["created_at"]

            store["users"][user_id] = merged
            self._write_store(store)
            return deepcopy(merged)

    def update_user(self, user_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        normalized = _normalize_value(updates)
        with self._lock:
            store = self._read_store()
            existing = store["users"].get(user_id)
            if not existing:
                return None

            updated = deepcopy(existing)
            updated.update(normalized)
            store["users"][user_id] = updated
            self._write_store(store)
            return deepcopy(updated)

    def update_user_settings(self, user_id: str, settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.update_user(user_id, {"settings": settings})

    def add_team_member(self, user_id: str, member: Dict[str, Any]) -> bool:
        normalized = _normalize_value(member)
        with self._lock:
            store = self._read_store()
            user = store["users"].get(user_id)
            if not user:
                return False

            members = list(user.get("team_members", []))
            members.append(normalized)
            user["team_members"] = members
            store["users"][user_id] = user
            self._write_store(store)
            return True

    def remove_team_member(self, user_id: str, email: str) -> bool:
        target = (email or "").lower()
        with self._lock:
            store = self._read_store()
            user = store["users"].get(user_id)
            if not user:
                return False

            members = user.get("team_members", [])
            filtered = [
                member for member in members
                if str(member.get("email", "")).lower() != target
            ]
            if len(filtered) == len(members):
                return False

            user["team_members"] = filtered
            store["users"][user_id] = user
            self._write_store(store)
            return True

    def get_team_members(self, user_id: str) -> List[Dict[str, Any]]:
        user = self.get_user_by_id(user_id)
        if not user:
            return []
        return deepcopy(user.get("team_members", []))

    # =========================================================================
    # Meeting Operations
    # =========================================================================

    def create_meeting(self, meeting_data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = _normalize_value(meeting_data)
        meeting_id = normalized["meeting_id"]

        with self._lock:
            store = self._read_store()
            existing = store["meetings"].get(meeting_id, {})
            merged = deepcopy(existing)
            merged.update(normalized)
            store["meetings"][meeting_id] = merged
            self._write_store(store)
            return deepcopy(merged)

    def get_meeting(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            meeting = self._read_store()["meetings"].get(meeting_id)
            return deepcopy(meeting) if meeting else None

    def update_meeting(self, meeting_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        normalized = _normalize_value(updates)
        normalized.setdefault("updated_at", datetime.utcnow().isoformat())

        with self._lock:
            store = self._read_store()
            meeting = store["meetings"].get(meeting_id)
            if not meeting:
                return None

            updated = deepcopy(meeting)
            updated.update(normalized)
            store["meetings"][meeting_id] = updated
            self._write_store(store)
            return deepcopy(updated)

    def delete_meeting(self, meeting_id: str) -> bool:
        with self._lock:
            store = self._read_store()
            if meeting_id not in store["meetings"]:
                return False
            del store["meetings"][meeting_id]
            self._write_store(store)
            return True

    def list_meetings(
        self,
        user_id: str,
        page: int = 1,
        limit: int = 10,
        search: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            meetings = [
                deepcopy(meeting)
                for meeting in self._read_store()["meetings"].values()
                if meeting.get("user_id") == user_id
            ]

        if status:
            meetings = [meeting for meeting in meetings if meeting.get("status") == status]
        if search:
            meetings = [meeting for meeting in meetings if self._match_search(meeting, search)]

        meetings.sort(key=lambda meeting: _parse_datetime(meeting.get("date")), reverse=True)

        total = len(meetings)
        start = max(page - 1, 0) * limit
        selected = meetings[start:start + limit]

        return {
            "meetings": [
                {
                    "meeting_id": meeting["meeting_id"],
                    "title": meeting.get("title"),
                    "date": meeting.get("date"),
                    "duration_seconds": meeting.get("duration_seconds"),
                    "status": meeting.get("status"),
                    "summary": meeting.get("summary"),
                    "task_count": len(meeting.get("tasks", [])),
                    "attendee_count": len(meeting.get("attendees", [])),
                }
                for meeting in selected
            ],
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": start + limit < total,
        }

    def list_all_meetings(
        self,
        page: int = 1,
        limit: int = 10,
        search: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            meetings = [
                deepcopy(meeting)
                for meeting in self._read_store()["meetings"].values()
            ]

        if status:
            meetings = [meeting for meeting in meetings if meeting.get("status") == status]
        if search:
            meetings = [meeting for meeting in meetings if self._match_search(meeting, search)]

        meetings.sort(key=lambda meeting: _parse_datetime(meeting.get("date")), reverse=True)

        total = len(meetings)
        start = max(page - 1, 0) * limit
        selected = meetings[start:start + limit]

        return {
            "meetings": [
                {
                    "meeting_id": meeting["meeting_id"],
                    "title": meeting.get("title"),
                    "date": meeting.get("date"),
                    "duration_seconds": meeting.get("duration_seconds"),
                    "status": meeting.get("status"),
                    "summary": meeting.get("summary"),
                    "task_count": len(meeting.get("tasks", [])),
                    "attendee_count": len(meeting.get("attendees", [])),
                    "user_id": meeting.get("user_id"),
                }
                for meeting in selected
            ],
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": start + limit < total,
        }

    def search_meetings(self, user_id: str, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            meetings = [
                deepcopy(meeting)
                for meeting in self._read_store()["meetings"].values()
                if meeting.get("user_id") == user_id and self._match_search(meeting, query)
            ]

        meetings.sort(key=lambda meeting: _parse_datetime(meeting.get("date")), reverse=True)
        return meetings[:limit]

    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            meetings = [
                deepcopy(meeting)
                for meeting in self._read_store()["meetings"].values()
                if meeting.get("user_id") == user_id
            ]

        meetings_by_status: Dict[str, int] = {}
        total_duration_seconds = 0
        total_tasks = 0

        for meeting in meetings:
            status = meeting.get("status", "unknown")
            meetings_by_status[status] = meetings_by_status.get(status, 0) + 1
            total_duration_seconds += int(meeting.get("duration_seconds") or 0)
            total_tasks += len(meeting.get("tasks", []))

        return {
            "total_meetings": len(meetings),
            "total_duration_seconds": total_duration_seconds,
            "meetings_by_status": meetings_by_status,
            "total_tasks": total_tasks,
        }


_storage_service: Optional[LocalStorageService] = None


def get_storage_service() -> LocalStorageService:
    """Get the local storage singleton."""
    global _storage_service
    if _storage_service is None:
        _storage_service = LocalStorageService()
    return _storage_service
