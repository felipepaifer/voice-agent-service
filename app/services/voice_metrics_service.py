from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import json
from threading import RLock
from typing import Deque, Dict, List


MAX_SAMPLES = 200
CONTAINER_METRICS_FILE = Path("/app/data/latency_metrics.json")
LOCAL_METRICS_FILE = Path("data/latency_metrics.json")

_lock = RLock()
_samples: Deque[Dict] = deque(maxlen=MAX_SAMPLES)


def _is_valid_numeric(value: object) -> bool:
    return isinstance(value, (int, float))


def _has_any_latency_value(sample: Dict) -> bool:
    return any(
        _is_valid_numeric(sample.get(key))
        for key in (
            "primary_response_ms",
            "end_to_end_response_ms",
            "stt_to_first_assistant_text_ms",
            "assistant_text_to_tts_start_ms",
            "stt_final_to_tts_start_ms",
        )
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


def record_latency_sample(
    *,
    turn: int,
    primary_response_ms: float | None,
    end_to_end_response_ms: float | None,
    stt_to_first_assistant_text_ms: float | None,
    assistant_text_to_tts_start_ms: float | None,
    stt_final_to_tts_start_ms: float | None,
    session_id: str | None = None,
) -> None:
    if turn <= 0:
        return
    if not any(
        _is_valid_numeric(value)
        for value in (
            primary_response_ms,
            end_to_end_response_ms,
            stt_to_first_assistant_text_ms,
            assistant_text_to_tts_start_ms,
            stt_final_to_tts_start_ms,
        )
    ):
        return
    sample = {
        "turn": int(turn),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "primary_response_ms": primary_response_ms,
        "end_to_end_response_ms": end_to_end_response_ms,
        "stt_to_first_assistant_text_ms": stt_to_first_assistant_text_ms,
        "assistant_text_to_tts_start_ms": assistant_text_to_tts_start_ms,
        "stt_final_to_tts_start_ms": stt_final_to_tts_start_ms,
        "session_id": (session_id or "").strip() or None,
    }
    with _lock:
        _samples.append(sample)
        persisted = _load_samples_from_disk()
        persisted.append(sample)
        _save_samples_to_disk(persisted)


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

    normalized_samples: List[Dict] = []
    for sample in samples:
        normalized = dict(sample)
        primary_response = normalized.get("primary_response_ms")
        if not isinstance(primary_response, (int, float)):
            fallback = normalized.get("stt_to_first_assistant_text_ms")
            if isinstance(fallback, (int, float)):
                normalized["primary_response_ms"] = float(fallback)
        normalized_samples.append(normalized)
    samples = normalized_samples

    def values_for(key: str) -> List[float]:
        values: List[float] = []
        for sample in samples:
            value = sample.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    primary_response = values_for("primary_response_ms")
    end_to_end_response = values_for("end_to_end_response_ms")
    stt_to_text = values_for("stt_to_first_assistant_text_ms")
    text_to_tts = values_for("assistant_text_to_tts_start_ms")
    stt_to_tts = values_for("stt_final_to_tts_start_ms")

    return {
        "window_size": MAX_SAMPLES,
        "sample_count": len(samples),
        "samples": samples[-30:],
        "session_id": latest_session_id,
        "summary": {
            "primary_response_ms": {
                "p50": _percentile(primary_response, 0.50),
                "p95": _percentile(primary_response, 0.95),
            },
            "end_to_end_response_ms": {
                "p50": _percentile(end_to_end_response, 0.50),
                "p95": _percentile(end_to_end_response, 0.95),
            },
            "stt_to_first_assistant_text_ms": {
                "p50": _percentile(stt_to_text, 0.50),
                "p95": _percentile(stt_to_text, 0.95),
            },
            "assistant_text_to_tts_start_ms": {
                "p50": _percentile(text_to_tts, 0.50),
                "p95": _percentile(text_to_tts, 0.95),
            },
            "stt_final_to_tts_start_ms": {
                "p50": _percentile(stt_to_tts, 0.50),
                "p95": _percentile(stt_to_tts, 0.95),
            },
        },
    }
