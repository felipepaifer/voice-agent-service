import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import elevenlabs, openai, silero

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.config import AppConfig
from app.services.config_service import load_config
from app.services.listings_service import search_listings
from app.services.availability_service import check_availability
from app.services.scheduling_service import schedule_viewing
from app.services.sms_service import send_sms_confirmation
from app.services.development_service import get_development_details
from app.services.session_context_service import get_user_id_for_room
from livekit_agent.prompts import (
    build_safety_prompt,
    build_system_prompt,
    build_tools_prompt,
)

logger = logging.getLogger("voice_latency")
HIGH_SIGNAL_METRICS = {
    "stt_metrics",
    "llm_metrics",
    "tts_metrics",
    "eou_metrics",
    "realtime_model_metrics",
}


@dataclass
class CallState:
    name: str = ""
    phone: str = ""
    listing_id: str = ""
    preferred_date: str = ""


VOICE_NAME_TO_ID = {
    # Legacy/default persona names mapped to ElevenLabs voice IDs.
    "rachel": "21m00Tcm4TlvDq8ikWAM",
}


class TurnLatencyTracker:
    def __init__(self) -> None:
        self.turn_id = 0
        self._turn_started_at = 0.0
        self._final_transcript_at = 0.0
        self._assistant_text_at = 0.0

    def mark_user_turn_started(self, transcript: str) -> None:
        self.turn_id += 1
        now = time.perf_counter()
        self._turn_started_at = now
        self._final_transcript_at = now
        self._assistant_text_at = 0.0
        logger.info(
            "turn=%s stage=stt_final transcript_chars=%s",
            self.turn_id,
            len(transcript or ""),
        )

    def mark_assistant_text_started(self) -> None:
        if self._assistant_text_at > 0:
            return
        self._assistant_text_at = time.perf_counter()
        logger.info(
            "turn=%s metric=stt_to_first_assistant_text_ms value=%.1f",
            self.turn_id,
            (self._assistant_text_at - self._final_transcript_at) * 1000,
        )

    def mark_speech_created(self) -> None:
        now = time.perf_counter()
        if self._assistant_text_at > 0:
            logger.info(
                "turn=%s metric=assistant_text_to_tts_start_ms value=%.1f",
                self.turn_id,
                (now - self._assistant_text_at) * 1000,
            )
        if self._turn_started_at > 0:
            logger.info(
                "turn=%s metric=stt_final_to_tts_start_ms value=%.1f",
                self.turn_id,
                (now - self._turn_started_at) * 1000,
            )


def _read_attr(event: object, key: str, default: object = None) -> object:
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def _is_assistant_message(event: object) -> bool:
    item = _read_attr(event, "item")
    role = _read_attr(item, "role")
    if isinstance(role, str):
        return role.lower() == "assistant"
    return False


def build_tts(
    api_key: str,
    persona_voice: str | None,
    default_voice_id: str | None,
    tts_model: str,
    streaming_latency: int,
) -> elevenlabs.TTS:
    if default_voice_id:
        return elevenlabs.TTS(
            api_key=api_key,
            voice_id=default_voice_id.strip(),
            model=tts_model,
            streaming_latency=streaming_latency,
            auto_mode=True,
        )

    if not persona_voice:
        return elevenlabs.TTS(
            api_key=api_key,
            model=tts_model,
            streaming_latency=streaming_latency,
            auto_mode=True,
        )

    normalized_voice = persona_voice.strip()
    mapped_voice_id = VOICE_NAME_TO_ID.get(normalized_voice.lower(), normalized_voice)
    return elevenlabs.TTS(
        api_key=api_key,
        voice_id=mapped_voice_id,
        model=tts_model,
        streaming_latency=streaming_latency,
        auto_mode=True,
    )


def _extract_user_id(identity: str) -> str | None:
    raw = (identity or "").strip()
    if not raw:
        return None
    if ":" in raw:
        candidate = raw.split(":", 1)[0].strip()
        return candidate or None
    return None


def _normalize_phone(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    has_plus = raw.startswith("+")
    digits_only = re.sub(r"\D", "", raw)
    if not digits_only:
        return ""
    return f"+{digits_only}" if has_plus else digits_only


def build_tools(config: dict, user_id: str) -> list[llm.FunctionTool]:
    state = CallState()
    notifications_cfg = dict(config.get("notifications", {}))
    default_phone = _normalize_phone(str(notifications_cfg.get("default_phone", "")))
    use_default_phone = bool(notifications_cfg.get("use_default_phone", False))
    require_phone_confirmation = bool(
        notifications_cfg.get("require_phone_confirmation", True)
    )

    def tool_enabled(key: str) -> bool:
        return bool(config.get("tools", {}).get(key, False))

    @llm.function_tool()
    async def get_development_details_tool(section: str = "overview") -> str:
        details = get_development_details(section=section)
        return json.dumps(details)

    @llm.function_tool()
    async def search_listings_tool() -> str:
        if not tool_enabled("search_listings"):
            return "Tool disabled."
        listings = search_listings(location="", budget=0, bedrooms=0)
        return json.dumps(listings)

    @llm.function_tool()
    async def check_availability_tool(date: str) -> str:
        if not tool_enabled("check_availability"):
            return "Tool disabled."
        state.preferred_date = date
        slots = check_availability(listing_id="", date=date)
        return json.dumps(slots)

    @llm.function_tool()
    async def schedule_viewing_tool(datetime: str, name: str, phone: str = "") -> str:
        if not tool_enabled("schedule_viewing"):
            return "Tool disabled."
        selected_phone = _normalize_phone(phone)
        if not selected_phone and use_default_phone and default_phone:
            selected_phone = default_phone
        if not selected_phone:
            selected_phone = state.phone
        state.name = name
        state.phone = selected_phone
        result = schedule_viewing(
            listing_id="",
            datetime=datetime,
            name=name,
            phone=selected_phone,
            user_id=user_id,
            create_calendar_event_enabled=tool_enabled("google_calendar_mcp"),
        )
        return json.dumps(result)

    @llm.function_tool()
    async def send_sms_confirmation_tool(
        phone: str = "",
        message: str = "",
        permission_granted: bool = False,
        phone_confirmed: bool = False,
    ) -> str:
        if not tool_enabled("send_sms_confirmation"):
            return "Tool disabled."
        selected_phone = _normalize_phone(phone) or state.phone
        if use_default_phone and default_phone:
            selected_phone = default_phone
        if require_phone_confirmation and not phone_confirmed:
            return json.dumps(
                {
                    "status": "blocked",
                    "reason": "Phone number not confirmed by user.",
                }
            )
        result = send_sms_confirmation(
            phone=selected_phone,
            message=message,
            permission_granted=permission_granted,
        )
        return json.dumps(result)

    return [
        get_development_details_tool,
        search_listings_tool,
        check_availability_tool,
        schedule_viewing_tool,
        send_sms_confirmation_tool,
    ]


async def entrypoint(ctx: JobContext):
    config = load_config()
    persona = config.get("persona", {})
    admin_system_prompt = str(config.get("system_prompt", "")).strip()

    system_prompt = build_system_prompt(
        persona_name=persona.get("name", "Alex"),
        greeting=persona.get("greeting", "Hi, this is Alex with Riverside Realty."),
        tools_enabled=config.get("tools", {}),
        development=config.get("development", {}),
        scheduling=config.get("scheduling", {}),
        notifications=config.get("notifications", {}),
    )
    prompt_sections = []
    if admin_system_prompt:
        prompt_sections.append(
            f"Operator Instructions (Admin UI): {admin_system_prompt}"
        )
    prompt_sections.extend(
        [
            system_prompt,
            build_safety_prompt(),
            build_tools_prompt(
                config.get("tools", {}),
                config.get("notifications", {}),
            ),
        ]
    )
    full_prompt = "\n".join(prompt_sections)

    env = AppConfig()
    def build_chained_agent_and_session(
        tools: list[llm.FunctionTool],
    ) -> tuple[Agent, AgentSession]:
        tts_engine = build_tts(
            env.ELEVENLABS_API_KEY,
            persona.get("voice"),
            env.ELEVENLABS_DEFAULT_VOICE_ID,
            env.ELEVENLABS_TTS_MODEL,
            env.ELEVENLABS_STREAMING_LATENCY,
        )
        vad_engine = silero.VAD.load()
        agent = Agent(
            instructions=full_prompt,
            tools=tools,
            vad=vad_engine,
            stt=openai.STT(model=env.OPENAI_STT_MODEL, api_key=env.OPENAI_API_KEY),
            llm=openai.LLM(model=env.OPENAI_LLM_MODEL, api_key=env.OPENAI_API_KEY),
            tts=tts_engine,
        )
        session = AgentSession(
            vad=vad_engine,
            stt=openai.STT(model=env.OPENAI_STT_MODEL, api_key=env.OPENAI_API_KEY),
            llm=openai.LLM(model=env.OPENAI_LLM_MODEL, api_key=env.OPENAI_API_KEY),
            tts=tts_engine,
            min_endpointing_delay=env.AGENT_MIN_ENDPOINTING_DELAY,
            max_endpointing_delay=env.AGENT_MAX_ENDPOINTING_DELAY,
            min_interruption_duration=env.AGENT_MIN_INTERRUPTION_DURATION,
            preemptive_generation=True,
        )
        return agent, session

    def build_realtime_agent_and_session(
        tools: list[llm.FunctionTool],
    ) -> tuple[Agent, AgentSession]:
        realtime_agent = Agent(
            instructions=full_prompt,
            tools=tools,
        )
        realtime_session = AgentSession(
            llm=openai.realtime.RealtimeModel(
                model=env.OPENAI_REALTIME_MODEL,
                voice=env.OPENAI_REALTIME_VOICE,
                api_key=env.OPENAI_API_KEY,
                input_audio_noise_reduction="near_field",
            ),
            min_endpointing_delay=env.AGENT_MIN_ENDPOINTING_DELAY,
            max_endpointing_delay=env.AGENT_MAX_ENDPOINTING_DELAY,
            min_interruption_duration=env.AGENT_MIN_INTERRUPTION_DURATION,
            preemptive_generation=True,
        )
        return realtime_agent, realtime_session

    def attach_observers(session: AgentSession, latency_tracker: TurnLatencyTracker) -> None:
        @session.on("user_input_transcribed")
        def on_user_input_transcribed(event):
            if bool(_read_attr(event, "is_final", False)):
                latency_tracker.mark_user_turn_started(
                    str(_read_attr(event, "transcript", ""))
                )

        @session.on("conversation_item_added")
        def on_conversation_item_added(event):
            if _is_assistant_message(event):
                latency_tracker.mark_assistant_text_started()

        @session.on("speech_created")
        def on_speech_created(_event):
            latency_tracker.mark_speech_created()

        @session.on("metrics_collected")
        def on_metrics_collected(event):
            metric_type = str(_read_attr(_read_attr(event, "metrics"), "type", ""))
            if metric_type in HIGH_SIGNAL_METRICS:
                logger.info("livekit_metrics event=%s", event)

    latency_tracker = TurnLatencyTracker()
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()

    inferred_user_id = _extract_user_id(str(getattr(participant, "identity", "")))
    room_user_id = get_user_id_for_room(str(getattr(ctx.room, "name", "")))
    user_id = inferred_user_id or room_user_id or "default-user"
    tools = build_tools(config, user_id=user_id)

    if env.OPENAI_REALTIME_ENABLED:
        try:
            agent, session = build_realtime_agent_and_session(tools)
            attach_observers(session, latency_tracker)
            logger.info(
                "agent_pipeline_config mode=realtime realtime_model=%s realtime_voice=%s endpointing=[%.2f, %.2f]",
                env.OPENAI_REALTIME_MODEL,
                env.OPENAI_REALTIME_VOICE,
                env.AGENT_MIN_ENDPOINTING_DELAY,
                env.AGENT_MAX_ENDPOINTING_DELAY,
            )
            await session.start(agent=agent, room=ctx.room)
            return
        except Exception:
            logger.exception(
                "realtime pipeline failed; falling back to chained pipeline"
            )

    agent, session = build_chained_agent_and_session(tools)
    attach_observers(session, latency_tracker)
    logger.info(
        "agent_pipeline_config mode=chained stt_model=%s llm_model=%s tts_model=%s tts_streaming_latency=%s endpointing=[%.2f, %.2f]",
        env.OPENAI_STT_MODEL,
        env.OPENAI_LLM_MODEL,
        env.ELEVENLABS_TTS_MODEL,
        env.ELEVENLABS_STREAMING_LATENCY,
        env.AGENT_MIN_ENDPOINTING_DELAY,
        env.AGENT_MAX_ENDPOINTING_DELAY,
    )
    await session.start(agent=agent, room=ctx.room)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
