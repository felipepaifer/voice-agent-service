from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import json
import logging
from threading import RLock
from typing import Deque, Dict, List, Tuple

from app.models.latency import TurnLatencyEvents

MAX_SAMPLES = 200
CONTAINER_METRICS_FILE = Path("/app/data/latency_metrics.json")
LOCAL_METRICS_FILE = Path("data/latency_metrics.json")
LATENCY_FIELDS = (
    "primary_response_perceived_ms",
    "end_to_end_response_ms",
    "stt_final_to_first_assistant_text_ms",
    "speech_start_to_text_commit_ms",
    "llm_time_to_first_token_ms",
    "tts_time_to_first_audio_ms",
)

LATENCY_METRIC_DEFINITIONS: Dict[str, Tuple[str, str]] = {
    "end_to_end_response_ms": ("speech_end_at", "first_audio_playback_at"),
}

logger = logging.getLogger("voice_latency")

_lock = RLock()
_samples: Deque[Dict] = deque(maxlen=MAX_SAMPLES)


def _is_valid_numeric(value: object) -> bool:
    return isinstance(value, (int, float))


def _has_any_latency_value(sample: Dict) -> bool:
    return any(
        _is_valid_numeric(sample.get(key))
        for key in LATENCY_FIELDS
    )


def _is_usable_sample(sample: Dict) -> bool:
    turn = sample.get("turn")
    if not isinstance(turn, int) or turn <= 0:
        return False
    return _has_any_latency_value(sample)


def _latest_session_id(samples: List[Dict]) -> str | None:
    for sample in reversed(samples):
        session_id = sample.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            return session_id.strip()
    return None


def _normalize_session_id(session_id: str | None) -> str | None:
    normalized = (session_id or "").strip()
    return normalized or None


def _matches_sample(sample: Dict, *, turn: int, session_id: str | None) -> bool:
    if sample.get("turn") != turn:
        return False
    existing_session = str(sample.get("session_id") or "").strip()
    if session_id:
        return existing_session == session_id
    return existing_session == ""


def _merge_sample(existing: Dict, incoming: Dict) -> Dict:
    merged = dict(existing)
    changed = False
    for key in LATENCY_FIELDS:
        value = incoming.get(key)
        if _is_valid_numeric(value):
            merged[key] = float(value)
            changed = True
    incoming_session_id = _normalize_session_id(incoming.get("session_id"))
    if incoming_session_id and merged.get("session_id") != incoming_session_id:
        merged["session_id"] = incoming_session_id
        changed = True
    if changed and incoming.get("timestamp"):
        merged["timestamp"] = incoming["timestamp"]
    return merged


def _upsert_sample(samples: List[Dict], incoming: Dict) -> List[Dict]:
    turn = int(incoming.get("turn", 0))
    session_id = _normalize_session_id(incoming.get("session_id"))
    for index, sample in enumerate(samples):
        if isinstance(sample, dict) and _matches_sample(
            sample, turn=turn, session_id=session_id
        ):
            samples[index] = _merge_sample(sample, incoming)
            return samples
    samples.append(incoming)
    return samples


def _metrics_file_path() -> Path:
    if CONTAINER_METRICS_FILE.parent.exists():
        return CONTAINER_METRICS_FILE
    return LOCAL_METRICS_FILE


def _load_samples_from_disk() -> List[Dict]:
    path = _metrics_file_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    samples = payload.get("samples")
    if not isinstance(samples, list):
        return []
    valid_samples: List[Dict] = []
    for sample in samples[-MAX_SAMPLES:]:
        if isinstance(sample, dict):
            valid_samples.append(sample)
    return valid_samples


def _save_samples_to_disk(samples: List[Dict]) -> None:
    path = _metrics_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"samples": samples[-MAX_SAMPLES:]}
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload), encoding="utf-8")
    temp_path.replace(path)


def _percentile(values: List[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    fraction = rank - lower_index
    return lower + (upper - lower) * fraction


def _duration_ms(
    metric_name: str,
    start: float | None,
    end: float | None,
    issues: List[str],
) -> float | None:
    if not _is_valid_numeric(start) or not _is_valid_numeric(end):
        return None
    duration = (float(end) - float(start)) * 1000
    if duration < 0:
        issues.append(
            f"{metric_name}: negative duration (start={start:.6f}, end={end:.6f})"
        )
        return None
    return duration


def _invalidate_metric(
    metrics: Dict[str, float | None],
    issues: List[str],
    metric_key: str,
    reason: str,
) -> None:
    if isinstance(metrics.get(metric_key), (int, float)):
        metrics[metric_key] = None
        issues.append(f"{metric_key}: {reason}")


def compute_latency_metrics(
    events: TurnLatencyEvents,
) -> Tuple[Dict[str, float | None], List[str]]:
    issues: List[str] = []
    metrics: Dict[str, float | None] = {key: None for key in LATENCY_FIELDS}

    # Keep API compatibility, but make only two KPIs authoritative:
    # 1) llm_time_to_first_token_ms (TTFT)
    # 2) end_to_end_response_ms
    if _is_valid_numeric(events.llm_time_to_first_token_ms):
        ttft_ms = float(events.llm_time_to_first_token_ms)
        if ttft_ms < 0:
            issues.append(f"llm_time_to_first_token_ms: negative duration ({ttft_ms:.3f})")
        else:
            metrics["llm_time_to_first_token_ms"] = ttft_ms
    else:
        metrics["llm_time_to_first_token_ms"] = _duration_ms(
            "llm_time_to_first_token_ms",
            events.llm_request_start_at,
            events.llm_first_token_at,
            issues,
        )

    for metric_key, (start_key, end_key) in LATENCY_METRIC_DEFINITIONS.items():
        start_value = getattr(events, start_key, None)
        end_value = getattr(events, end_key, None)
        metrics[metric_key] = _duration_ms(metric_key, start_value, end_value, issues)

    return metrics, issues


def record_latency_events(
    *,
    events: TurnLatencyEvents,
    session_id: str | None = None,
) -> None:
    if events.turn_id <= 0:
        return
    metrics, issues = compute_latency_metrics(events)
    if issues:
        logger.info(
            "turn=%s metric_validation issues=%s",
            events.turn_id,
            "; ".join(issues),
        )
    if not any(_is_valid_numeric(value) for value in metrics.values()):
        return
    record_latency_sample(
        turn=events.turn_id,
        session_id=session_id,
        primary_response_perceived_ms=metrics.get("primary_response_perceived_ms"),
        end_to_end_response_ms=metrics.get("end_to_end_response_ms"),
        stt_final_to_first_assistant_text_ms=metrics.get(
            "stt_final_to_first_assistant_text_ms"
        ),
        speech_start_to_text_commit_ms=metrics.get("speech_start_to_text_commit_ms"),
        llm_time_to_first_token_ms=metrics.get("llm_time_to_first_token_ms"),
        tts_time_to_first_audio_ms=metrics.get("tts_time_to_first_audio_ms"),
    )


def record_latency_sample(
    *,
    turn: int,
    primary_response_perceived_ms: float | None,
    end_to_end_response_ms: float | None,
    stt_final_to_first_assistant_text_ms: float | None,
    speech_start_to_text_commit_ms: float | None,
    llm_time_to_first_token_ms: float | None,
    tts_time_to_first_audio_ms: float | None,
    session_id: str | None = None,
) -> None:
    if turn <= 0:
        return
    if not any(
        _is_valid_numeric(value)
        for value in (
            primary_response_perceived_ms,
            end_to_end_response_ms,
            stt_final_to_first_assistant_text_ms,
            speech_start_to_text_commit_ms,
            llm_time_to_first_token_ms,
            tts_time_to_first_audio_ms,
        )
    ):
        return
    sample = {
        "turn": int(turn),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "primary_response_perceived_ms": primary_response_perceived_ms,
        "end_to_end_response_ms": end_to_end_response_ms,
        "stt_final_to_first_assistant_text_ms": stt_final_to_first_assistant_text_ms,
        "speech_start_to_text_commit_ms": speech_start_to_text_commit_ms,
        "llm_time_to_first_token_ms": llm_time_to_first_token_ms,
        "tts_time_to_first_audio_ms": tts_time_to_first_audio_ms,
        "session_id": _normalize_session_id(session_id),
    }
    with _lock:
        persisted = _load_samples_from_disk()
        _upsert_sample(persisted, sample)
        _save_samples_to_disk(persisted)

        in_memory = list(_samples)
        _upsert_sample(in_memory, sample)
        _samples.clear()
        _samples.extend(in_memory[-MAX_SAMPLES:])


def get_latency_metrics_snapshot() -> Dict:
    with _lock:
        disk_samples = _load_samples_from_disk()
        if disk_samples:
            _samples.clear()
            _samples.extend(
                [sample for sample in disk_samples[-MAX_SAMPLES:] if _is_usable_sample(sample)]
            )
        samples = [sample for sample in list(_samples) if _is_usable_sample(sample)]

    latest_session_id = _latest_session_id(samples)
    if latest_session_id:
        filtered_samples = [
            sample
            for sample in samples
            if str(sample.get("session_id", "")).strip() == latest_session_id
        ]
        if filtered_samples:
            samples = filtered_samples

    def values_for(key: str) -> List[float]:
        values: List[float] = []
        for sample in samples:
            value = sample.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    primary_response = values_for("primary_response_perceived_ms")
    end_to_end_response = values_for("end_to_end_response_ms")
    stt_to_text = values_for("stt_final_to_first_assistant_text_ms")
    speech_to_text_commit = values_for("speech_start_to_text_commit_ms")
    llm_ttft = values_for("llm_time_to_first_token_ms")
    tts_ttfa = values_for("tts_time_to_first_audio_ms")

    return {
        "window_size": MAX_SAMPLES,
        "sample_count": len(samples),
        "samples": samples[-30:],
        "session_id": latest_session_id,
        "summary": {
            "primary_response_perceived_ms": {
                "p50": _percentile(primary_response, 0.50),
                "p95": _percentile(primary_response, 0.95),
            },
            "end_to_end_response_ms": {
                "p50": _percentile(end_to_end_response, 0.50),
                "p95": _percentile(end_to_end_response, 0.95),
            },
            "stt_final_to_first_assistant_text_ms": {
                "p50": _percentile(stt_to_text, 0.50),
                "p95": _percentile(stt_to_text, 0.95),
            },
            "speech_start_to_text_commit_ms": {
                "p50": _percentile(speech_to_text_commit, 0.50),
                "p95": _percentile(speech_to_text_commit, 0.95),
            },
            "llm_time_to_first_token_ms": {
                "p50": _percentile(llm_ttft, 0.50),
                "p95": _percentile(llm_ttft, 0.95),
            },
            "tts_time_to_first_audio_ms": {
                "p50": _percentile(tts_ttfa, 0.50),
                "p95": _percentile(tts_ttfa, 0.95),
            },
        },
    }
