from dataclasses import dataclass
from typing import Dict

LATENCY_EVENT_FIELDS = (
    "speech_start_at",
    "speech_end_at",
    "text_commit_at",
    "stt_final_at",
    "llm_request_start_at",
    "llm_first_token_at",
    "llm_time_to_first_token_ms",
    "llm_complete_at",
    "tts_request_start_at",
    "tts_first_audio_chunk_at",
    "first_audio_playback_at",
    "first_audio_playback_source",
    "first_audio_playback_fallback_at",
    "first_audio_playback_fallback_source",
)


@dataclass
class TurnLatencyEvents:
    turn_id: int
    speech_start_at: float | None = None
    speech_end_at: float | None = None
    text_commit_at: float | None = None
    stt_final_at: float | None = None
    llm_request_start_at: float | None = None
    llm_first_token_at: float | None = None
    llm_time_to_first_token_ms: float | None = None
    llm_complete_at: float | None = None
    tts_request_start_at: float | None = None
    tts_first_audio_chunk_at: float | None = None
    first_audio_playback_at: float | None = None
    first_audio_playback_source: str | None = None
    first_audio_playback_fallback_at: float | None = None
    first_audio_playback_fallback_source: str | None = None

    def as_dict(self) -> Dict[str, float | None]:
        return {field: getattr(self, field) for field in LATENCY_EVENT_FIELDS}
