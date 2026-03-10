# Aloware Backend - Real Estate Voice Agent

Backend-only repo for a LiveKit voice agent that schedules real estate viewings.

## Setup (< 5 minutes)

Prerequisites:

- Docker + Docker Compose
- API keys configured in `.env`

1. Copy env example:
   ```bash
   cp .env.example .env
   ```
2. Add API keys in `.env` (at minimum: `OPENAI_API_KEY`, `ADMIN_API_KEY`, and LiveKit vars if you are creating sessions).
3. Start the server:
   ```bash
   docker-compose up --build
   ```

This starts:

- `backend` on `http://localhost:8000`
- `agent` worker (`app/agents/livekit/agent.py`)

If you only want the API server:

```bash
docker-compose up --build backend
```

## API Authentication

All `/api/*` endpoints (except Google OAuth callback) require the header:

`x-api-key: <ADMIN_API_KEY>`

If `ADMIN_API_KEY` is missing, protected endpoints return a server configuration error.

## Running the LiveKit Agent

The agent reads `data/config.json` for prompt/persona/tools and can use either:

- OpenAI Realtime (`OPENAI_REALTIME_ENABLED=true`)
- Chained STT -> LLM -> TTS (`OPENAI_REALTIME_ENABLED=false`)

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

Example:

```bash
curl -X POST http://localhost:8000/api/agent/session \
  -H "Content-Type: application/json" \
  -H "x-api-key: $ADMIN_API_KEY" \
  -d '{"room":"real-estate-demo","user_id":"user-123"}'
```

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

- Flask app factory + layered structure (routes/controllesrs/services/models).
- JSON files for config and bookings to avoid database setup.
- Tool-level guardrails: SMS requires explicit permission.
- Prompts are modular in `app/agents/livekit/prompts` with variable injection.
- Booking writes are committed only after calendar provider success when calendar integration is enabled.

## What I'd Improve with More Time

- Production authentication.
- Multi-user session isolation and tenant-aware config so concurrent calls never share state or tools.
- Queue-based post-call analysis pipeline (Celery/Redis) for transcript summarization, QA scoring, and follow-up actions without blocking live calls.
- Stronger resilience patterns for real-time workloads: retries, idempotency keys, and dead-letter handling for failed tasks.
- Automated behavior tests for critical tool-calling flows and guardrails.

## Bonus (Optional)

I picked **Latency** as the bonus. The agent emits per-turn latency logs with a timestamp chain so we can quickly locate where response delay is introduced and tune the pipeline without changing core business logic. With more time, I would extend this into a queue-based post-call analysis worker (Celery/Redis) that aggregates turn-level metrics and transcript insights for QA and continuous prompt/tool optimization.