"""Thread-safe JSON storage used by the VND RSVP prototype.

This module intentionally keeps persistence simple for the first pilot. Replace it
with Postgres before multiple workers or a public web dashboard are introduced.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent / "data"
_ATTENDEES = _DATA_DIR / "attendees.json"
_EVENT = _DATA_DIR / "event.json"
_LOCK = threading.RLock()

VALID_STATUSES = {
    "pending",
    "confirmed",
    "declined",
    "maybe",
    "callback_requested",
    "question_pending",
    "no_answer",
    "wrong_number",
    "voicemail",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def get_event() -> dict[str, Any]:
    return _read_json(_EVENT)


def list_attendees() -> list[dict[str, Any]]:
    return _read_json(_ATTENDEES)


def get_attendee(attendee_id: str) -> dict[str, Any] | None:
    return next((a for a in list_attendees() if a["id"] == attendee_id), None)


def update_attendee(attendee_id: str, **changes: Any) -> dict[str, Any]:
    status = changes.get("status")
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    with _LOCK:
        attendees = _read_json(_ATTENDEES)
        for attendee in attendees:
            if attendee["id"] != attendee_id:
                continue
            attendee.update(changes)
            attendee["updated_at"] = _now_iso()
            _write_json(_ATTENDEES, attendees)
            return attendee

    raise KeyError(f"Attendee {attendee_id} not found")


def increment_attempts(attendee_id: str) -> int:
    attendee = get_attendee(attendee_id)
    if not attendee:
        raise KeyError(f"Attendee {attendee_id} not found")
    attempts = int(attendee.get("attempts", 0)) + 1
    update_attendee(attendee_id, attempts=attempts, last_call_at=_now_iso())
    return attempts


def append_call_history(
    attendee_id: str,
    *,
    outcome: str,
    summary: str = "",
) -> dict[str, Any]:
    with _LOCK:
        attendees = _read_json(_ATTENDEES)
        for attendee in attendees:
            if attendee["id"] != attendee_id:
                continue
            history = attendee.setdefault("call_history", [])
            history.append(
                {
                    "at": _now_iso(),
                    "outcome": outcome,
                    "summary": summary,
                }
            )
            attendee["updated_at"] = _now_iso()
            _write_json(_ATTENDEES, attendees)
            return attendee
    raise KeyError(f"Attendee {attendee_id} not found")


def add_question(attendee_id: str, question: str) -> dict[str, Any]:
    cleaned = question.strip()
    if not cleaned:
        raise ValueError("Question cannot be empty")

    with _LOCK:
        attendees = _read_json(_ATTENDEES)
        for attendee in attendees:
            if attendee["id"] != attendee_id:
                continue
            questions = attendee.setdefault("questions", [])
            questions.append(
                {
                    "question": cleaned,
                    "status": "open",
                    "created_at": _now_iso(),
                }
            )
            attendee["status"] = "question_pending"
            attendee["updated_at"] = _now_iso()
            _write_json(_ATTENDEES, attendees)
            return attendee
    raise KeyError(f"Attendee {attendee_id} not found")
