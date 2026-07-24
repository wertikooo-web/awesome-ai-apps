"""VND/WineMD outbound RSVP agent powered by OpenAI Realtime.

Run as a LiveKit worker:
    uv run python agent.py dev
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import openai
from loguru import logger

import prompts
import tools as db

load_dotenv(override=True)


@dataclass
class CallState:
    attendee_id: str
    attendee: dict[str, Any]
    event: dict[str, Any]


class VNDRSVPAgent(Agent):
    def __init__(self, state: CallState) -> None:
        self.state = state
        super().__init__(instructions=prompts.build_instructions(state.attendee, state.event))

    @function_tool()
    async def confirm_attendance(
        self,
        context: RunContext,
        guests_count: int,
        confirmation_summary: str = "",
    ) -> dict[str, Any]:
        """Confirm attendance only after the person explicitly confirms the final recap.

        Args:
            guests_count: Additional guests, excluding the invited attendee.
            confirmation_summary: Short summary of the explicit confirmation.
        """
        guest_limit = int(self.state.attendee.get("guest_limit", 0))
        if guests_count < 0 or guests_count > guest_limit:
            return {
                "ok": False,
                "error": f"guests_count must be between 0 and {guest_limit}",
            }

        updated = db.update_attendee(
            self.state.attendee_id,
            status="confirmed",
            guests=guests_count,
            callback_at=None,
            notes=confirmation_summary.strip(),
        )
        db.append_call_history(
            self.state.attendee_id,
            outcome="confirmed",
            summary=confirmation_summary or f"Confirmed with {guests_count} additional guests.",
        )
        logger.info("Confirmed {} (+{})", updated["name"], guests_count)
        return {"ok": True, "status": "confirmed", "guests": guests_count}

    @function_tool()
    async def decline_attendance(
        self,
        context: RunContext,
        reason: str = "",
    ) -> dict[str, Any]:
        """Record an explicit refusal to attend.

        Args:
            reason: Optional short reason volunteered by the attendee.
        """
        updated = db.update_attendee(
            self.state.attendee_id,
            status="declined",
            guests=0,
            callback_at=None,
            notes=reason.strip(),
        )
        db.append_call_history(
            self.state.attendee_id,
            outcome="declined",
            summary=reason.strip(),
        )
        logger.info("Declined {}: {!r}", updated["name"], reason)
        return {"ok": True, "status": "declined"}

    @function_tool()
    async def mark_maybe(
        self,
        context: RunContext,
        note: str = "",
    ) -> dict[str, Any]:
        """Record that the attendee remains uncertain.

        Args:
            note: Short explanation or useful follow-up context.
        """
        db.update_attendee(
            self.state.attendee_id,
            status="maybe",
            notes=note.strip(),
        )
        db.append_call_history(
            self.state.attendee_id,
            outcome="maybe",
            summary=note.strip(),
        )
        return {"ok": True, "status": "maybe"}

    @function_tool()
    async def schedule_callback(
        self,
        context: RunContext,
        callback_at: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Save the attendee's requested callback date/time phrase.

        Args:
            callback_at: Clear date/time phrase in the attendee's own timezone.
            note: Optional context for the next call.
        """
        if not callback_at.strip():
            return {"ok": False, "error": "callback_at is required"}
        db.update_attendee(
            self.state.attendee_id,
            status="callback_requested",
            callback_at=callback_at.strip(),
            notes=note.strip(),
        )
        db.append_call_history(
            self.state.attendee_id,
            outcome="callback_requested",
            summary=f"{callback_at.strip()} | {note.strip()}".strip(" |"),
        )
        return {
            "ok": True,
            "status": "callback_requested",
            "callback_at": callback_at.strip(),
        }

    @function_tool()
    async def save_question_for_organizer(
        self,
        context: RunContext,
        question: str,
    ) -> dict[str, Any]:
        """Save a question that cannot be answered from the event facts.

        Args:
            question: The attendee's question, summarized faithfully.
        """
        db.add_question(self.state.attendee_id, question)
        db.append_call_history(
            self.state.attendee_id,
            outcome="question_pending",
            summary=question.strip(),
        )
        return {"ok": True, "status": "question_pending"}

    @function_tool()
    async def mark_wrong_number(
        self,
        context: RunContext,
        note: str = "",
    ) -> dict[str, Any]:
        """Mark that the dialed number does not belong to the intended attendee.

        Args:
            note: Optional short detail about the wrong number.
        """
        db.update_attendee(
            self.state.attendee_id,
            status="wrong_number",
            notes=note.strip(),
        )
        db.append_call_history(
            self.state.attendee_id,
            outcome="wrong_number",
            summary=note.strip(),
        )
        return {"ok": True, "status": "wrong_number"}

    @function_tool()
    async def end_call(
        self,
        context: RunContext,
        summary: str = "",
    ) -> dict[str, str]:
        """End the call after the outcome or follow-up has been recorded.

        Args:
            summary: Optional final call summary.
        """
        logger.info("Ending call with {}: {}", self.state.attendee["name"], summary)
        await context.session.aclose()
        return {"status": "ended"}


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    metadata: dict[str, Any] = {}
    if ctx.job.metadata:
        try:
            metadata = json.loads(ctx.job.metadata)
        except json.JSONDecodeError:
            logger.warning("Could not parse job metadata: {!r}", ctx.job.metadata)

    attendee_id = metadata.get("attendee_id")
    if not attendee_id:
        logger.error("No attendee_id in job metadata; aborting")
        return

    attendee = db.get_attendee(attendee_id)
    if not attendee:
        logger.error("Unknown attendee_id={}; aborting", attendee_id)
        return

    db.increment_attempts(attendee_id)
    state = CallState(
        attendee_id=attendee_id,
        attendee=attendee,
        event=db.get_event(),
    )

    model = openai.realtime.RealtimeModel(
        model=os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime"),
        voice=os.getenv("OPENAI_REALTIME_VOICE", "marin"),
    )
    session = AgentSession(llm=model)

    await session.start(room=ctx.room, agent=VNDRSVPAgent(state))
    first_name = attendee["name"].split()[0]
    language = attendee.get("language", "ru").lower()
    opening_instruction = (
        f"Începe apelul acum. Salută-l pe {first_name}, spune clar că ești un "
        "asistent vocal automat și întreabă dacă participă la eveniment."
        if language == "ro"
        else f"Начни звонок. Обратись к {first_name}, ясно скажи, что ты "
        "автоматический голосовой помощник, и спроси об участии в мероприятии."
    )
    await session.generate_reply(instructions=opening_instruction)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.getenv("AGENT_NAME", "vnd-rsvp-agent"),
        )
    )
