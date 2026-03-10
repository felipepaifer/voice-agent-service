# Aloware Backend - Real Estate Voice Agent

Backend-only repo for a LiveKit voice agent that schedules real estate viewings.

## Setup (< 5 minutes)

1. Copy env example:
   ```bash
   cp .env.example .env
   ```
2. Add API keys in `.env`.
3. Build and run:
   ```bash
   docker-compose up --build
   ```

Backend runs on `http://localhost:8000`.

## Running the LiveKit Agent

The LiveKit agent is an optional service. Start it with:

```bash
docker-compose --profile agent up --build
```

The agent reads `data/config.json` for prompt/persona/tools.

## LiveKit Setup

You can use LiveKit Cloud or a local LiveKit server.

Required env vars:

```
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
```

Voice mode env vars:

```
OPENAI_REALTIME_ENABLED=true
OPENAI_REALTIME_MODEL=gpt-realtime
OPENAI_REALTIME_VOICE=marin
```

When realtime mode is enabled, the agent uses OpenAI realtime speech for lower latency
and keeps your existing tool-calling behavior. Set `OPENAI_REALTIME_ENABLED=false` to
fall back to the chained STT -> LLM -> TTS pipeline.

The backend endpoint `POST /api/agent/session` returns a token, room, identity, and URL.

## Google Calendar OAuth (Per User)

The backend supports per-user Google Calendar connection and event creation during
`schedule_viewing` calls.

Required env vars:

```
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/admin/google/callback
GOOGLE_CALENDAR_SCOPES=https://www.googleapis.com/auth/calendar.events
```

API endpoints:

- `POST /api/admin/google/connect` (requires `x-api-key`) -> returns OAuth URL
- `GET /api/admin/google/callback` (Google redirect endpoint)
- `GET /api/admin/google/status?user_id=...` (requires `x-api-key`)
- `POST /api/admin/google/disconnect` (requires `x-api-key`)

When a user is connected, new viewings create a Google Calendar event first, then
persist into `data/bookings.json` only after provider success.

## Why LiveKit Agents SDK

LiveKit Agents provides built-in real-time audio handling, tool-calling, and a clean
VoicePipelineAgent API, so we can focus on the phone experience and tools rather
than building a custom audio pipeline.

## Design Decisions

- Flask app factory + layered structure (routes/controllers/services/models).
- JSON files for config and bookings to avoid database setup.
- Tool-level guardrails: SMS requires explicit permission.
- Prompts are modular in `livekit_agent/prompts` with variable injection.

## What I'd Improve with More Time

- Robust session state tracking and retries.
- Better intent handling and slot filling.
- Twilio voice/PSTN integration for real phone calls.
- Automated tests for tool invocation.

## Bonus (Optional)

The agent now emits latency-focused logs per turn (STT final -> first assistant text
-> TTS start). You can inspect these logs from the `agent` container to identify
whether delay is mostly STT, LLM generation, or TTS startup.

## Latency Measurement Methodology

The latency dashboard reports turn-level metrics intended to approximate user-perceived
responsiveness in live calls:

- `primary_response_ms`: headline perceived-response KPI (realtime TTFT when available, otherwise first assistant text timing)
- `end_to_end_response_ms`: from final user transcript to assistant speech start (preferred), with TTFT fallback when speech-start events are unavailable
- `stt_to_first_assistant_text_ms`: from final user transcript to first assistant text
- `assistant_text_to_tts_start_ms`: from first assistant text to speech creation
- `stt_final_to_tts_start_ms`: diagnostic timing from final transcript to speech lifecycle creation

For realtime mode, assistant text events can be delayed or absent. In those cases,
the tracker uses realtime model TTFT as the preferred primary-response signal and
also as a fallback proxy for first assistant response timing.

To improve data quality, the tracker excludes non-usable rows from reporting:

- cancelled realtime turns
- turns without any numeric latency values
- synthetic/invalid turn ids (`turn <= 0`)

The dashboard uses percentile summaries (`p50`, `p95`) over a rolling in-memory/file
window to show both typical latency and worst-case spikes during demos.
