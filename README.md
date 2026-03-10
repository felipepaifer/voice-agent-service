# Aloware Voice Agent Backend (Python + LiveKit)

Backend repository for a real-time voice agent that handles a real-estate developer
assistant scenario (project info + viewing scheduling + confirmations).

## Setup (Under 5 Minutes)

1. Copy env template:
   ```bash
   cp .env.example .env
   ```
2. Fill API keys in `.env` (OpenAI, LiveKit, optional ElevenLabs/Twilio/Google).
3. Run backend + agent:
   ```bash
   docker-compose up --build
   ```

Backend API: `http://localhost:8000`

## Companion Frontend Repo

The React admin UI lives in a separate repository (`aloware-next`), which configures:
- System prompt/instructions
- Persona (name, greeting)
- Tool availability

## Why LiveKit Agents SDK (instead of Pipecat)

I chose LiveKit Agents SDK because it offers:
- Fast path to real-time voice interactions (room/session primitives)
- Built-in tool calling and event lifecycle hooks
- Practical STT/LLM/TTS/realtime model integrations with minimal boilerplate

Given the one-day constraint, this enabled focus on call quality and orchestration
instead of custom audio plumbing.

## What I Built

- Real-time voice agent for a single development use case
- Tool orchestration with toggles from admin config
- Scheduling policy (time window, slot size, conflict prevention)
- SMS confirmation flow with permission + phone confirmation guardrails
- Optional per-user Google Calendar event creation during scheduling
- Runtime prompt composition from:
  - Admin UI instructions (`system_prompt`)
  - behavioral prompt
  - safety prompt
  - tools prompt

## Tools Used in Conversation

At least 3 tools are available and exercised:
- `check_availability_tool`
- `schedule_viewing_tool`
- `send_sms_confirmation_tool`
- `get_development_details_tool` (factual grounding)

## Guardrails / Safety

- Explicit phone number confirmation before SMS
- Explicit user permission before SMS send
- Prompt-level safety constraints for sensitive data handling
- Tool-level validation for phone format and provider responses

## Bonus Chosen: Latency

I chose latency because voice UX breaks quickly when response timing drifts.
In voice, 200ms vs 800ms feels much larger than in chat due to turn-taking and
barge-in expectations.

Implemented:
- Turn-level latency instrumentation (STT final -> first assistant text -> TTS start)
- Realtime model path with fallback to chained pipeline

## Key API Endpoints

- `POST /api/agent/session` -> room/identity/token/url for voice client
- `POST /api/agent/call` -> SMS trigger endpoint
- `GET /api/admin/config` -> fetch agent config
- `POST /api/admin/config` -> update agent config
- `POST /api/admin/google/connect`
- `GET /api/admin/google/callback`
- `GET /api/admin/google/status`
- `POST /api/admin/google/disconnect`

## Design Decisions

- Layered structure: routes -> controllers -> services -> models
- JSON storage for one-day implementation simplicity (no DB by design)
- Prompt modules to keep behavior maintainable
- Config-driven tool gating for fast operator iteration

## What I'd Improve with More Time

- Add automated evals for tool selection and parameter correctness
- Move persistence from JSON to transactional storage
- Add stronger auth/rate-limiting hardening for non-local environments
- Add integration tests for scheduling + provider failure modes
