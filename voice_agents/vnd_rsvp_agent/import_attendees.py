"""Import attendees from a CSV file into data/attendees.json.

Expected columns:
    id,name,phone,language,guest_limit,notes

Usage:
    uv run python import_attendees.py path/to/attendees.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

REQUIRED_COLUMNS = {"id", "name", "phone"}
SUPPORTED_LANGUAGES = {"ru", "ro"}


def normalize_phone(value: str) -> str:
    phone = "".join(ch for ch in value.strip() if ch.isdigit() or ch == "+")
    if not phone.startswith("+") or len(phone) < 8:
        raise ValueError(f"Phone must use E.164 format, got: {value!r}")
    return phone


def load_rows(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

        attendees: list[dict] = []
        seen_ids: set[str] = set()
        seen_phones: set[str] = set()

        for row_number, row in enumerate(reader, start=2):
            attendee_id = (row.get("id") or "").strip()
            name = (row.get("name") or "").strip()
            phone = normalize_phone(row.get("phone") or "")
            language = (row.get("language") or "ru").strip().lower()

            if not attendee_id or not name:
                raise ValueError(f"Row {row_number}: id and name are required")
            if attendee_id in seen_ids:
                raise ValueError(f"Row {row_number}: duplicate id {attendee_id}")
            if phone in seen_phones:
                raise ValueError(f"Row {row_number}: duplicate phone {phone}")
            if language not in SUPPORTED_LANGUAGES:
                raise ValueError(f"Row {row_number}: language must be ru or ro")

            try:
                guest_limit = int((row.get("guest_limit") or "0").strip())
            except ValueError as exc:
                raise ValueError(f"Row {row_number}: guest_limit must be an integer") from exc
            if guest_limit < 0:
                raise ValueError(f"Row {row_number}: guest_limit cannot be negative")

            attendees.append(
                {
                    "id": attendee_id,
                    "name": name,
                    "phone": phone,
                    "language": language,
                    "status": "pending",
                    "guest_limit": guest_limit,
                    "guests": 0,
                    "attempts": 0,
                    "notes": (row.get("notes") or "").strip(),
                    "callback_at": None,
                    "questions": [],
                    "call_history": [],
                }
            )
            seen_ids.add(attendee_id)
            seen_phones.add(phone)

    return attendees


def main() -> None:
    parser = argparse.ArgumentParser(description="Import RSVP attendees from CSV")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "attendees.json",
    )
    args = parser.parse_args()

    attendees = load_rows(args.csv_path)
    args.output.write_text(
        json.dumps(attendees, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Imported {len(attendees)} attendee(s) into {args.output}")


if __name__ == "__main__":
    main()
