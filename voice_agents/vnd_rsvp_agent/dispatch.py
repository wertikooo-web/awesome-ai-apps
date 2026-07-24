"""Place outbound RSVP calls through a configured LiveKit SIP trunk.

Examples:
    uv run python dispatch.py --dry-run
    uv run python dispatch.py --id A1
    uv run python dispatch.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid

from dotenv import load_dotenv
from livekit import api
from loguru import logger

import tools as db

load_dotenv(override=True)

ELIGIBLE_STATUSES = {"pending", "callback_requested", "no_answer", "voicemail"}


def max_attempts() -> int:
    return int(os.getenv("MAX_ATTEMPTS", "2"))


def pacing_seconds() -> float:
    return float(os.getenv("CALL_PACING_SECONDS", "2"))


def eligible(attendee: dict) -> bool:
    return (
        attendee.get("status", "pending") in ELIGIBLE_STATUSES
        and int(attendee.get("attempts", 0)) < max_attempts()
    )


async def dial_attendee(lkapi: api.LiveKitAPI, attendee: dict) -> None:
    trunk_id = os.environ["SIP_OUTBOUND_TRUNK_ID"]
    agent_name = os.getenv("AGENT_NAME", "vnd-rsvp-agent")
    room_name = f"vnd-rsvp-{attendee['id']}-{uuid.uuid4().hex[:8]}"
    metadata = json.dumps({"attendee_id": attendee["id"]})

    logger.info("Dialing {} ({})", attendee["name"], attendee["phone"])

    await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=agent_name,
            room=room_name,
            metadata=metadata,
        )
    )

    try:
        await lkapi.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=trunk_id,
                sip_call_to=attendee["phone"],
                room_name=room_name,
                participant_identity=f"callee-{attendee['id']}",
                participant_name=attendee["name"],
                participant_metadata=metadata,
                krisp_enabled=True,
                wait_until_answered=True,
            )
        )
    except Exception as exc:
        logger.exception("SIP call failed for {}: {}", attendee["name"], exc)
        attempts = int(attendee.get("attempts", 0)) + 1
        status = "no_answer" if attempts >= max_attempts() else attendee.get("status", "pending")
        db.update_attendee(
            attendee["id"],
            attempts=attempts,
            status=status,
            notes=f"Dial failure: {type(exc).__name__}",
        )
        db.append_call_history(
            attendee["id"],
            outcome="dial_failure",
            summary=str(exc)[:300],
        )


async def main(only_id: str | None, dry_run: bool) -> None:
    if only_id:
        attendee = db.get_attendee(only_id)
        if not attendee:
            raise SystemExit(f"Attendee {only_id} not found")
        targets = [attendee]
    else:
        targets = [attendee for attendee in db.list_attendees() if eligible(attendee)]

    if not targets:
        logger.info("No eligible attendees to dial")
        return

    logger.info("Selected {} attendee(s)", len(targets))
    if dry_run:
        for attendee in targets:
            logger.info(
                "DRY RUN: {} | {} | {} | attempts={}",
                attendee["id"],
                attendee["name"],
                attendee["phone"],
                attendee.get("attempts", 0),
            )
        return

    lkapi = api.LiveKitAPI()
    try:
        for attendee in targets:
            await dial_attendee(lkapi, attendee)
            await asyncio.sleep(pacing_seconds())
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dispatch VND RSVP calls")
    parser.add_argument("--id", help="Dial only one attendee id, for example A1")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List selected attendees without placing calls",
    )
    args = parser.parse_args()
    asyncio.run(main(only_id=args.id, dry_run=args.dry_run))
