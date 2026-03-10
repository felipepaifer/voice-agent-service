import json
import inspect
import logging
import os
import re
import sys
import time
from dataclasses import dataclass

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import elevenlabs, openai, silero
from openai.types import realtime as openai_realtime_types

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from app.agents.livekit.prompts import (
    build_safety_prompt,
    build_system_prompt,
    build_tools_prompt,
)
from app.config import AppConfig
from app.services.availability_service import check_availability
from app.services.config_service import load_config
from app.services.development_service import get_development_details
from app.services.scheduling_service import schedule_viewing
from app.services.session_context_service import get_user_id_for_room
from app.services.sms_service import send_sms_confirmation
from app.models.latency import TurnLatencyEvents
from app.services.voice_metrics_service import record_latency_events

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
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.turn_id = 0
        self._events: TurnLatencyEvents | None = None
        self._metric_epoch_offset = time.time() - time.monotonic()
        self._pending_speech_start_at: float | None = None
        self._pending_speech_end_at: float | None = None
        self._pending_llm_request_start_at: float | None = None
        self._pending_llm_first_token_at: float | None = None
        self._pending_llm_time_to_first_token_ms: float | None = None
        self._pending_llm_complete_at: float | None = None
        self._pending_tts_request_start_at: float | None = None
        self._pending_tts_first_audio_chunk_at: float | None = None
        self._pending_first_audio_playback_at: float | None = None
        self._pending_first_audio_playback_source: str | None = None
        self._pending_first_audio_playback_fallback_at: float | None = None
        self._pending_first_audio_playback_fallback_source: str | None = None
        self._awaiting_turn_commit = False
        self._user_speaking_active = False
        self._last_logged_turn = 0

    def _has_open_turn(self) -> bool:
        return bool(self._events and self._events.turn_id > 0)

    def _should_buffer_for_next_turn(self) -> bool:
        return self._awaiting_turn_commit

    def _set_pending_earliest(self, attr_name: str, value: float) -> None:
        current = getattr(self, attr_name)
        if not isinstance(current, (int, float)) or value < current:
            setattr(self, attr_name, value)

    def _set_pending_latest(self, attr_name: str, value: float) -> None:
        current = getattr(self, attr_name)
        if not isinstance(current, (int, float)) or value > current:
            setattr(self, attr_name, value)

    def _clear_pending(self) -> None:
        self._pending_speech_start_at = None
        self._pending_speech_end_at = None
        self._pending_llm_request_start_at = None
        self._pending_llm_first_token_at = None
        self._pending_llm_time_to_first_token_ms = None
        self._pending_llm_complete_at = None
        self._pending_tts_request_start_at = None
        self._pending_tts_first_audio_chunk_at = None
        self._pending_first_audio_playback_at = None
        self._pending_first_audio_playback_source = None
        self._pending_first_audio_playback_fallback_at = None
        self._pending_first_audio_playback_fallback_source = None

    def _normalize_metric_timestamp(self, value: float) -> float:
        # Some providers emit monotonic-like timestamps while others emit unix epoch.
        # Normalize to epoch seconds so all duration math uses one clock domain.
        if value < 1_000_000_000:
            return self._metric_epoch_offset + value
        return value

    def _record_turn_metrics(self) -> None:
        if not self._events:
            return
        record_latency_events(events=self._events, session_id=self.session_id)
        self._maybe_log_event_chain()

    def _maybe_log_event_chain(self) -> None:
        if not self._events or self._events.turn_id == self._last_logged_turn:
            return
        if not isinstance(self._events.first_audio_playback_at, (int, float)):
            return
        base_label = None
        base_time = None
        if isinstance(self._events.speech_start_at, (int, float)):
            base_label = "speech_start_at"
            base_time = self._events.speech_start_at
        elif isinstance(self._events.text_commit_at, (int, float)):
            base_label = "text_commit_at"
            base_time = self._events.text_commit_at
        elif isinstance(self._events.stt_final_at, (int, float)):
            base_label = "stt_final_at"
            base_time = self._events.stt_final_at
        if base_label is None or base_time is None:
            return
        deltas_ms = {}
        for key, value in self._events.as_dict().items():
            if key == "llm_time_to_first_token_ms":
                # This field is already a duration in ms, not an absolute timestamp.
                deltas_ms[key] = round(float(value), 2) if isinstance(value, (int, float)) else None
                continue
            if key.endswith("_source"):
                deltas_ms[key] = value if isinstance(value, str) else None
                continue
            if isinstance(value, (int, float)):
                deltas_ms[key] = round((value - base_time) * 1000, 2)
            else:
                deltas_ms[key] = None
        logger.info(
            "turn=%s latency_event_chain base=%s deltas_ms=%s",
            self._events.turn_id,
            base_label,
            deltas_ms,
        )
        self._last_logged_turn = self._events.turn_id

    def mark_user_speech_started(self) -> None:
        now = time.time()
        self._awaiting_turn_commit = True
        self._user_speaking_active = True
        self._set_pending_earliest("_pending_speech_start_at", now)

    def mark_user_speech_ended(self) -> None:
        if not self._user_speaking_active:
            return
        now = time.time()
        self._awaiting_turn_commit = True
        self._user_speaking_active = False
        self._set_pending_latest("_pending_speech_end_at", now)

    def mark_user_turn_committed(self, transcript: str) -> None:
        del transcript
        self.turn_id += 1
        now = time.time()
        events = TurnLatencyEvents(turn_id=self.turn_id)
        if isinstance(self._pending_speech_start_at, (int, float)):
            events.speech_start_at = self._pending_speech_start_at
        events.speech_end_at = self._pending_speech_end_at
        events.text_commit_at = now

        if isinstance(self._pending_llm_request_start_at, (int, float)):
            events.llm_request_start_at = self._pending_llm_request_start_at
        if isinstance(self._pending_llm_first_token_at, (int, float)):
            events.llm_first_token_at = self._pending_llm_first_token_at
        if isinstance(self._pending_llm_time_to_first_token_ms, (int, float)):
            events.llm_time_to_first_token_ms = self._pending_llm_time_to_first_token_ms
        if isinstance(self._pending_llm_complete_at, (int, float)):
            events.llm_complete_at = self._pending_llm_complete_at
        if isinstance(self._pending_tts_request_start_at, (int, float)):
            events.tts_request_start_at = self._pending_tts_request_start_at
        if isinstance(self._pending_tts_first_audio_chunk_at, (int, float)):
            events.tts_first_audio_chunk_at = self._pending_tts_first_audio_chunk_at
        if isinstance(self._pending_first_audio_playback_at, (int, float)):
            events.first_audio_playback_at = self._pending_first_audio_playback_at
            events.first_audio_playback_source = self._pending_first_audio_playback_source
        if isinstance(self._pending_first_audio_playback_fallback_at, (int, float)):
            events.first_audio_playback_fallback_at = (
                self._pending_first_audio_playback_fallback_at
            )
            events.first_audio_playback_fallback_source = (
                self._pending_first_audio_playback_fallback_source
            )
        if (
            not isinstance(events.first_audio_playback_at, (int, float))
            and isinstance(events.first_audio_playback_fallback_at, (int, float))
        ):
            fallback_delay_ms = None
            if isinstance(events.speech_end_at, (int, float)):
                fallback_delay_ms = (
                    events.first_audio_playback_fallback_at - events.speech_end_at
                ) * 1000
            logger.info(
                "turn=%s missing_strict_playback fallback_source=%s fallback_delay_ms=%s",
                events.turn_id,
                events.first_audio_playback_fallback_source or "unknown",
                f"{fallback_delay_ms:.2f}" if isinstance(fallback_delay_ms, (int, float)) else "n/a",
            )

        self._events = events
        self._clear_pending()
        self._awaiting_turn_commit = False
        self._user_speaking_active = False
        self._record_turn_metrics()

    def mark_llm_first_token(self) -> None:
        now = time.time()
        if not self._has_open_turn() and not self._should_buffer_for_next_turn():
            return
        if self._should_buffer_for_next_turn() or not self._has_open_turn():
            self._set_pending_earliest("_pending_llm_first_token_at", now)
            return
        if isinstance(self._events.llm_first_token_at, (int, float)):
            return
        self._events.llm_first_token_at = now
        self._record_turn_metrics()

    def mark_tts_request_started(self) -> None:
        now = time.time()
        if not self._has_open_turn() and not self._should_buffer_for_next_turn():
            return
        if self._should_buffer_for_next_turn() or not self._has_open_turn():
            self._set_pending_earliest("_pending_tts_request_start_at", now)
            return
        if isinstance(self._events.tts_request_start_at, (int, float)):
            return
        self._events.tts_request_start_at = now
        self._record_turn_metrics()

    def mark_first_audio_playback(self, source: str, *, strict: bool = True) -> None:
        now = time.time()
        if not self._has_open_turn() and not self._should_buffer_for_next_turn():
            # Ignore out-of-turn assistant playback (e.g. greeting/stray audio) so it
            # cannot be attached to the next user turn.
            logger.info(
                "latency_playback_mark ignored source=%s strict=%s reason=no_open_turn",
                source,
                strict,
            )
            return
        if self._should_buffer_for_next_turn() or not self._has_open_turn():
            if strict:
                if not isinstance(self._pending_first_audio_playback_at, (int, float)) or now < float(
                    self._pending_first_audio_playback_at
                ):
                    self._pending_first_audio_playback_at = now
                    self._pending_first_audio_playback_source = source
                    logger.info(
                        "latency_playback_mark buffered_primary source=%s strict=%s",
                        source,
                        strict,
                    )
                self._set_pending_earliest("_pending_tts_first_audio_chunk_at", now)
                if (
                    isinstance(self._pending_llm_request_start_at, (int, float))
                    and not isinstance(self._pending_llm_first_token_at, (int, float))
                ):
                    # Fallback for turns where provider TTFT is absent: use first confirmed
                    # playback signal as proxy for first model output timing.
                    self._set_pending_earliest("_pending_llm_first_token_at", now)
            else:
                if not isinstance(
                    self._pending_first_audio_playback_fallback_at, (int, float)
                ) or now < float(self._pending_first_audio_playback_fallback_at):
                    self._pending_first_audio_playback_fallback_at = now
                    self._pending_first_audio_playback_fallback_source = source
                    logger.info(
                        "latency_playback_mark buffered_fallback source=%s strict=%s",
                        source,
                        strict,
                    )
            return

        if strict:
            if not isinstance(self._events.tts_first_audio_chunk_at, (int, float)):
                self._events.tts_first_audio_chunk_at = now
            if not isinstance(self._events.first_audio_playback_at, (int, float)):
                self._events.first_audio_playback_at = now
                self._events.first_audio_playback_source = source
                logger.info(
                    "latency_playback_mark set_primary source=%s strict=%s",
                    source,
                    strict,
                )
            if (
                isinstance(self._events.llm_request_start_at, (int, float))
                and not isinstance(self._events.llm_first_token_at, (int, float))
            ):
                # Fallback only when direct TTFT is unavailable.
                self._events.llm_first_token_at = now
        else:
            if not isinstance(self._events.first_audio_playback_fallback_at, (int, float)):
                self._events.first_audio_playback_fallback_at = now
                self._events.first_audio_playback_fallback_source = source
                logger.info(
                    "latency_playback_mark set_fallback source=%s strict=%s",
                    source,
                    strict,
                )
        self._record_turn_metrics()

    def mark_llm_metrics(self, metrics: object) -> None:
        metric_type = str(_read_attr(metrics, "type", ""))
        timestamp = _read_attr(metrics, "timestamp")
        ttft = _read_attr(metrics, "ttft")
        duration = _read_attr(metrics, "duration")
        if not isinstance(timestamp, (int, float)):
            return
        start_at = self._normalize_metric_timestamp(float(timestamp))
        ttft_ms = float(ttft) * 1000 if isinstance(ttft, (int, float)) else None
        first_token_at = (
            start_at + float(ttft) if isinstance(ttft, (int, float)) else None
        )
        complete_at = (
            start_at + float(duration) if isinstance(duration, (int, float)) else None
        )

        # Realtime ttft is first audio token, not first text token.
        can_set_text_first_token = metric_type == "llm_metrics"

        if not self._has_open_turn() and not self._should_buffer_for_next_turn():
            return
        if self._should_buffer_for_next_turn() or not self._has_open_turn():
            self._set_pending_earliest("_pending_llm_request_start_at", start_at)
            if can_set_text_first_token and isinstance(first_token_at, (int, float)):
                self._set_pending_earliest("_pending_llm_first_token_at", first_token_at)
            if isinstance(ttft_ms, (int, float)):
                self._set_pending_earliest("_pending_llm_time_to_first_token_ms", ttft_ms)
            if isinstance(complete_at, (int, float)):
                self._set_pending_latest("_pending_llm_complete_at", complete_at)
            return

        if not isinstance(self._events.llm_request_start_at, (int, float)):
            self._events.llm_request_start_at = start_at
        if (
            can_set_text_first_token
            and isinstance(first_token_at, (int, float))
            and not isinstance(self._events.llm_first_token_at, (int, float))
        ):
            self._events.llm_first_token_at = first_token_at
        if (
            isinstance(complete_at, (int, float))
            and not isinstance(self._events.llm_complete_at, (int, float))
        ):
            self._events.llm_complete_at = complete_at
        if isinstance(ttft_ms, (int, float)) and not isinstance(
            self._events.llm_time_to_first_token_ms, (int, float)
        ):
            self._events.llm_time_to_first_token_ms = ttft_ms
        self._record_turn_metrics()

    def mark_tts_metrics(self, metrics: object) -> None:
        timestamp = _read_attr(metrics, "timestamp")
        ttfb = _read_attr(metrics, "ttfb")
        if not isinstance(timestamp, (int, float)):
            return
        start_at = self._normalize_metric_timestamp(float(timestamp))
        first_audio_at = (
            start_at + float(ttfb) if isinstance(ttfb, (int, float)) else None
        )

        if self._should_buffer_for_next_turn() or not self._has_open_turn():
            self._set_pending_earliest("_pending_tts_request_start_at", start_at)
            if isinstance(first_audio_at, (int, float)):
                self._set_pending_earliest(
                    "_pending_tts_first_audio_chunk_at", first_audio_at
                )
            return

        if not isinstance(self._events.tts_request_start_at, (int, float)):
            self._events.tts_request_start_at = start_at
        if (
            isinstance(first_audio_at, (int, float))
            and not isinstance(self._events.tts_first_audio_chunk_at, (int, float))
        ):
            self._events.tts_first_audio_chunk_at = first_audio_at
        self._record_turn_metrics()


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

    tools: list[llm.FunctionTool] = [
        get_development_details_tool,
        check_availability_tool,
        schedule_viewing_tool,
    ]
    if tool_enabled("send_sms_confirmation"):
        tools.append(send_sms_confirmation_tool)
    return tools


async def entrypoint(ctx: JobContext):
    config = load_config()
    persona = config.get("persona", {})
    admin_system_prompt = str(config.get("system_prompt", "")).strip()
    sms_enabled = bool(config.get("tools", {}).get("send_sms_confirmation", True))

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
    if not sms_enabled:
        prompt_sections.append(
            "SMS confirmation is disabled in tools settings. "
            "Do not offer SMS, do not ask for permission to text, and ignore any conflicting SMS instruction."
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
                modalities=["text", "audio"],
                input_audio_transcription=openai_realtime_types.AudioTranscription(
                    model="gpt-4o-transcribe",
                ),
                input_audio_noise_reduction="near_field",
                turn_detection=openai_realtime_types.realtime_audio_input_turn_detection.SemanticVad(
                    type="semantic_vad",
                    create_response=True,
                    eagerness="auto",
                    interrupt_response=True,
                ),
            ),
            min_endpointing_delay=env.AGENT_MIN_ENDPOINTING_DELAY,
            max_endpointing_delay=env.AGENT_MAX_ENDPOINTING_DELAY,
            min_interruption_duration=env.AGENT_MIN_INTERRUPTION_DURATION,
            preemptive_generation=True,
        )
        return realtime_agent, realtime_session

    def attach_observers(
        session: AgentSession,
        latency_tracker: TurnLatencyTracker,
        room: object,
        user_identity: str,
    ) -> None:
        @session.on("user_input_transcribed")
        def on_user_input_transcribed(event):
            transcript = str(_read_attr(event, "transcript", ""))
            if transcript.strip():
                latency_tracker.mark_user_speech_started()
            if bool(_read_attr(event, "is_final", False)):
                latency_tracker.mark_user_turn_committed(transcript)

        @session.on("conversation_item_added")
        def on_conversation_item_added(event):
            if _is_assistant_message(event):
                latency_tracker.mark_llm_first_token()

        @session.on("speech_created")
        def on_speech_created(event):
            speech_handle = _read_attr(event, "speech_handle") or _read_attr(
                event, "speechHandle"
            )
            handle_type = type(speech_handle).__name__ if speech_handle else "None"
            logger.info(
                "speech_created source=%s handle=%s",
                _read_attr(event, "source", ""),
                handle_type,
            )
            if speech_handle is not None:
                public_attrs = sorted(
                    [name for name in dir(speech_handle) if not name.startswith("_")]
                )
                logger.info(
                    "speech_handle_public_attrs handle=%s attrs=%s",
                    handle_type,
                    public_attrs,
                )
            on_method = getattr(speech_handle, "on", None)
            registered_callbacks = 0
            if callable(on_method):
                for event_name in (
                    "playout_started",
                    "speech_started",
                    "started",
                    "playout_start",
                    "audio_started",
                    "audio_start",
                    "speech_start",
                    "playout_begin",
                ):
                    try:
                        def _mark_speech_started(
                            _event=None, callback_event_name: str = event_name
                        ):
                            logger.info(
                                "speech_handle_callback_fired event=%s",
                                callback_event_name,
                            )
                            latency_tracker.mark_first_audio_playback(
                                source=f"speech_handle:{callback_event_name}",
                                strict=True,
                            )

                        on_method(event_name, _mark_speech_started)
                        registered_callbacks += 1
                    except Exception:
                        logger.info(
                            "speech_handle_callback_registration_failed event=%s",
                            event_name,
                        )
                        continue
            else:
                logger.info("speech_handle_has_no_on_method handle=%s", handle_type)

            # Some SDK versions expose dedicated callback methods instead of emitter .on(...)
            for callback_method_name in (
                "on_playout_started",
                "on_speech_started",
                "on_audio_started",
                "on_started",
            ):
                callback_method = getattr(speech_handle, callback_method_name, None)
                if not callable(callback_method):
                    continue
                try:
                    def _mark_via_method(
                        _event=None, method_name: str = callback_method_name
                    ):
                        logger.info(
                            "speech_handle_method_callback_fired method=%s",
                            method_name,
                        )
                        latency_tracker.mark_first_audio_playback(
                            source=f"speech_handle_method:{method_name}",
                            strict=True,
                        )

                    callback_method(_mark_via_method)
                    registered_callbacks += 1
                    logger.info(
                        "speech_handle_method_callback_registered method=%s",
                        callback_method_name,
                    )
                except Exception:
                    logger.info(
                        "speech_handle_method_callback_registration_failed method=%s",
                        callback_method_name,
                    )

            add_listener = getattr(speech_handle, "add_listener", None)
            if callable(add_listener):
                for event_name in ("playout_started", "speech_started", "audio_started"):
                    try:
                        def _mark_via_listener(
                            _event=None, listener_event_name: str = event_name
                        ):
                            logger.info(
                                "speech_handle_listener_fired event=%s",
                                listener_event_name,
                            )
                            latency_tracker.mark_first_audio_playback(
                                source=f"speech_handle_listener:{listener_event_name}",
                                strict=True,
                            )

                        add_listener(event_name, _mark_via_listener)
                        registered_callbacks += 1
                        logger.info(
                            "speech_handle_listener_registered event=%s",
                            event_name,
                        )
                    except Exception:
                        logger.info(
                            "speech_handle_listener_registration_failed event=%s",
                            event_name,
                        )
            logger.info(
                "speech_created callback_registration_count=%s",
                registered_callbacks,
            )
            latency_tracker.mark_tts_request_started()

        @session.on("agent_started_speaking")
        def on_agent_started_speaking(_event):
            logger.info("agent_started_speaking event received")
            latency_tracker.mark_first_audio_playback(
                source="session:agent_started_speaking",
                strict=False,
            )

        @session.on("speech_started")
        def on_speech_started(_event):
            logger.info("speech_started event received")
            latency_tracker.mark_first_audio_playback(
                source="session:speech_started",
                strict=True,
            )

        @session.on("agent_state_changed")
        def on_agent_state_changed(event):
            new_state = str(_read_attr(event, "new_state", "")).lower()
            old_state = str(_read_attr(event, "old_state", "")).lower()
            logger.info(
                "agent_state_changed new_state=%s old_state=%s",
                new_state,
                old_state,
            )
            if "speaking" in new_state:
                # Keep this as diagnostic fallback only. It should not feed primary KPI.
                latency_tracker.mark_first_audio_playback(
                    source="agent_state_changed:speaking",
                    strict=False,
                )

        @session.on("user_state_changed")
        def on_user_state_changed(event):
            new_state = str(_read_attr(event, "new_state", "")).lower()
            old_state = str(_read_attr(event, "old_state", "")).lower()
            logger.info(
                "user_state_changed new_state=%s old_state=%s",
                new_state,
                old_state,
            )
            if "speaking" in new_state:
                latency_tracker.mark_user_speech_started()
            # Only close a user turn when we actually transition out of speaking.
            if "listening" in new_state and "speaking" in old_state:
                latency_tracker.mark_user_speech_ended()

        @session.on("metrics_collected")
        def on_metrics_collected(event):
            metrics = _read_attr(event, "metrics")
            metric_type = str(_read_attr(metrics, "type", ""))
            if metric_type in ("llm_metrics", "realtime_model_metrics"):
                latency_tracker.mark_llm_metrics(metrics)
            if metric_type == "tts_metrics":
                latency_tracker.mark_tts_metrics(metrics)
            if metric_type in HIGH_SIGNAL_METRICS:
                logger.info("livekit_metrics event=%s", event)

        room_on = getattr(room, "on", None)
        room_listener_count = 0
        if callable(room_on):
            def _participant_identity(payload: object) -> str:
                participant = _read_attr(payload, "participant")
                if participant is None:
                    participant = payload
                return str(_read_attr(participant, "identity", "")).strip()

            def _is_agent_speaking_payload(payload: object) -> bool:
                participant_identity = _participant_identity(payload)
                if participant_identity and participant_identity == user_identity:
                    return False
                speaking = _read_attr(payload, "is_speaking")
                if isinstance(speaking, bool):
                    return speaking
                speaking = _read_attr(payload, "isSpeaking")
                if isinstance(speaking, bool):
                    return speaking
                # Some payloads only expose "speaking" for participant-like objects.
                speaking = _read_attr(payload, "speaking")
                if isinstance(speaking, bool):
                    return speaking
                return False

            def _on_is_speaking_changed(event):
                participant_identity = _participant_identity(event)
                logger.info(
                    "room_is_speaking_changed identity=%s is_speaking=%s",
                    participant_identity or "unknown",
                    _read_attr(event, "is_speaking", _read_attr(event, "isSpeaking", None)),
                )
                if _is_agent_speaking_payload(event):
                    latency_tracker.mark_first_audio_playback(
                        source="room:is_speaking_changed",
                        strict=True,
                    )

            def _on_active_speakers_changed(event):
                speakers = None
                if isinstance(event, list):
                    speakers = event
                else:
                    candidate = _read_attr(event, "speakers")
                    if isinstance(candidate, list):
                        speakers = candidate
                    else:
                        candidate = _read_attr(event, "active_speakers")
                        if isinstance(candidate, list):
                            speakers = candidate
                if not isinstance(speakers, list):
                    logger.info(
                        "room_active_speakers_changed_unhandled payload_type=%s",
                        type(event).__name__,
                    )
                    return
                speaker_ids = [
                    str(_read_attr(speaker, "identity", "")).strip() for speaker in speakers
                ]
                logger.info(
                    "room_active_speakers_changed ids=%s payload_type=%s",
                    speaker_ids,
                    type(event).__name__,
                )
                for speaker in speakers:
                    identity = str(_read_attr(speaker, "identity", "")).strip()
                    if identity and identity == user_identity:
                        continue
                    latency_tracker.mark_first_audio_playback(
                        source="room:active_speakers_changed",
                        strict=True,
                    )
                    break

            for event_name, callback in (
                ("is_speaking_changed", _on_is_speaking_changed),
                ("IsSpeakingChanged", _on_is_speaking_changed),
                ("active_speakers_changed", _on_active_speakers_changed),
                ("ActiveSpeakersChanged", _on_active_speakers_changed),
            ):
                try:
                    room_on(event_name, callback)
                    room_listener_count += 1
                    logger.info("room_listener_registered event=%s", event_name)
                except Exception:
                    logger.info("room_listener_registration_failed event=%s", event_name)
                    continue
        logger.info("room_listener_registration_count=%s", room_listener_count)

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    room_sid = getattr(ctx.room, "sid", "")
    if inspect.isawaitable(room_sid):
        try:
            room_sid = await room_sid
        except Exception:
            room_sid = ""
    room_identifier = (
        str(room_sid).strip()
        or str(getattr(ctx.room, "name", "")).strip()
        or "unknown-session"
    )
    latency_tracker = TurnLatencyTracker(session_id=room_identifier)
    try:
        participant = await ctx.wait_for_participant()
    except RuntimeError as exc:
        # Happens when the room closes before participant join finishes.
        # Treat this as a normal early-disconnect lifecycle event.
        logger.warning("room closed before participant joined: %s", exc)
        return

    inferred_user_id = _extract_user_id(str(getattr(participant, "identity", "")))
    room_user_id = get_user_id_for_room(str(getattr(ctx.room, "name", "")))
    user_id = inferred_user_id or room_user_id or "default-user"
    tools = build_tools(config, user_id=user_id)

    if env.OPENAI_REALTIME_ENABLED:
        try:
            agent, session = build_realtime_agent_and_session(tools)
            attach_observers(
                session,
                latency_tracker,
                room=ctx.room,
                user_identity=str(getattr(participant, "identity", "")).strip(),
            )
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
    attach_observers(
        session,
        latency_tracker,
        room=ctx.room,
        user_identity=str(getattr(participant, "identity", "")).strip(),
    )
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
