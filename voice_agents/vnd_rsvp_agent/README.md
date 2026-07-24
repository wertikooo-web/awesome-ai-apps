# VND RSVP Voice Agent

Outbound multilingual voice agent for VND/WineMD event confirmations. It calls attendees through LiveKit Telephony, uses OpenAI Realtime for natural speech-to-speech conversation, and records structured outcomes in a JSON prototype database.

## Current MVP

The agent can:

- call one attendee or every eligible attendee;
- speak Russian or Romanian according to the attendee record;
- answer event questions from `data/event.json`;
- handle interruptions and requests to repeat information;
- confirm attendance and additional guest count;
- record declines, uncertainty, callback requests, unanswered questions, and wrong numbers;
- keep a basic call history;
- import attendees from CSV;
- run a dry run before any real calls.

The agent must identify itself as an automated voice assistant. It must never invent missing event information or treat a vague answer as confirmation.

## Architecture

```text
CSV / future web dashboard
        |
        v
attendees.json (prototype storage)
        |
        v
dispatch.py
        |
        v
LiveKit room + outbound SIP call
        |
        v
OpenAI Realtime agent.py
        |
        v
structured tool calls -> attendees.json
```

LiveKit remains the telephony and realtime transport layer. OpenAI Realtime handles speech understanding, dialogue, audio generation, and turn taking.

## Files

| File | Purpose |
|---|---|
| `agent.py` | OpenAI Realtime voice agent and structured tools |
| `dispatch.py` | Selects attendees and places outbound SIP calls |
| `prompts.py` | Russian/Romanian conversation policy and event grounding |
| `tools.py` | Thread-safe JSON prototype storage |
| `import_attendees.py` | Imports a CSV list into `attendees.json` |
| `data/event.json` | Event details and FAQ |
| `data/attendees.json` | Prototype attendee database |
| `data/attendees_template.csv` | CSV template for organizers |
| `.env.example` | Required keys and settings |

## Setup

Requirements:

- Python 3.10 or newer;
- `uv`;
- LiveKit Cloud project;
- outbound SIP trunk configured in LiveKit;
- OpenAI API key with Realtime access.

```bash
cd voice_agents/vnd_rsvp_agent
cp .env.example .env
uv sync
```

Fill in `.env`:

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
SIP_OUTBOUND_TRUNK_ID=ST_...
OPENAI_API_KEY=...
OPENAI_REALTIME_MODEL=gpt-realtime
OPENAI_REALTIME_VOICE=marin
AGENT_NAME=vnd-rsvp-agent
```

Use real phone numbers in E.164 format, for example `+373...`.

## Prepare an event

Edit `data/event.json`. Every answer the agent is allowed to provide should be present there. Unknown details should stay explicitly unconfirmed rather than guessed.

Minimum event fields:

```json
{
  "name": "VND Partner Evening",
  "host": "VND",
  "date": "2026-09-18",
  "start_time": "18:00",
  "end_time": "21:30",
  "venue": "Venue name",
  "address": "Full address",
  "guest_policy": "One additional guest is allowed",
  "contact_phone": "+373...",
  "faq": {}
}
```

## Import attendees

Copy `data/attendees_template.csv` and fill it in:

```csv
id,name,phone,language,guest_limit,notes
A1,Alexei Example,+373...,ru,1,
A2,Ion Exemplu,+373...,ro,1,
```

Import:

```bash
uv run python import_attendees.py path/to/attendees.csv
```

The importer rejects missing columns, duplicate IDs, duplicate phone numbers, unsupported languages, and invalid phone formats.

## Run a safe dry run

```bash
uv run python dispatch.py --dry-run
```

This lists selected contacts without calling anyone.

## Start the worker

Terminal 1:

```bash
uv run python agent.py dev
```

## Test one number

Terminal 2:

```bash
uv run python dispatch.py --id A1
```

Use your own phone number for the first tests. Deliberately interrupt the agent, ask it to repeat the address, change the guest count, say "maybe", and request a callback. Check `data/attendees.json` after every call.

## Launch a batch

```bash
uv run python dispatch.py
```

Only eligible records under the retry limit are selected. Control retry and pacing through:

```dotenv
MAX_ATTEMPTS=2
CALL_PACING_SECONDS=2
```

## Data rules

The stored `guests` value means additional guests and excludes the invited attendee.

Statuses:

- `pending`
- `confirmed`
- `declined`
- `maybe`
- `callback_requested`
- `question_pending`
- `no_answer`
- `wrong_number`
- `voicemail`

An explicit final confirmation is required before `confirmed` is written. Requests above `guest_limit` are sent to the organizer as questions.

## Important prototype limitations

This package uses a local JSON file. It is suitable for local testing and a tightly controlled pilot with one worker. It is not safe for a public multi-user dashboard or several concurrent workers.

Before production, replace JSON storage with Postgres and add:

- authentication and company workspaces;
- event creation form;
- `.xlsx`/CSV upload and validation;
- test-call button;
- call queue with allowed calling hours;
- live campaign results;
- callback and organizer-question inbox;
- audit log and cost controls;
- consent, retention, recording, and privacy settings appropriate to the countries where calls are made.

## Planned WineMD dashboard

A non-technical WineMD employee should use a protected web page:

```text
Create campaign
-> enter event details and FAQ
-> upload Excel list
-> review validation errors
-> place a test call to themselves
-> approve estimated call count/cost
-> launch campaign
-> view confirmations, declines, callbacks, questions, and exports
```

The dashboard should write to the same domain model used here. The Realtime agent and call dispatcher should remain backend services hidden from the organizer.

## Recommended validation sequence

1. Ten calls to the project owner.
2. Five internal VND/WineMD staff calls.
3. Twenty invited testers who know they may receive an automated call.
4. Review every transcript/outcome manually.
5. Only then run a real event campaign.
