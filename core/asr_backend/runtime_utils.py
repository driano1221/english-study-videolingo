"""Pure helpers for adaptive, profile-driven local ASR."""

from __future__ import annotations

import re

import numpy as np


PROFILES = {
    "free": {
        "label": "Grátis",
        "vad_onset": 0.50,
        "vad_offset": 0.36,
        "repair_max_gaps": 0,
        "repair_min_gap": 1.0,
        "repair_max_gap": 8.0,
    },
    "balanced": {
        "label": "Equilibrado",
        "vad_onset": 0.42,
        "vad_offset": 0.30,
        "repair_max_gaps": 8,
        "repair_min_gap": 0.8,
        "repair_max_gap": 10.0,
    },
    "robust": {
        "label": "Máxima robustez",
        "vad_onset": 0.32,
        "vad_offset": 0.22,
        "repair_max_gaps": 24,
        "repair_min_gap": 0.5,
        "repair_max_gap": 15.0,
    },
}


def profile_settings(name: str) -> dict:
    key = str(name or "balanced").strip().lower()
    if key not in PROFILES:
        raise ValueError(f"Perfil de inferência inválido: {name}")
    return {"name": key, **PROFILES[key]}


def is_capacity_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        token in text
        for token in ("out of memory", "cuda", "cublas", "cudnn", "batch", "memory")
    )


def run_batch_fallback(call, batches=(4, 2, 1)):
    """Try a transcription call at decreasing batches; return result and winner."""
    last_error = None
    for batch in batches:
        try:
            return call(batch), batch
        except Exception as exc:
            if not is_capacity_error(exc) or batch == batches[-1]:
                raise
            last_error = exc
    raise last_error  # pragma: no cover


def hotwords_from_metadata(metadata: dict, max_chars=480) -> str:
    """Extract useful names/terms from a YouTube title and description."""
    title = str(metadata.get("title") or "").strip()
    description = str(metadata.get("description") or "").strip()[:3000]
    candidates = [title]
    candidates.extend(re.findall(r"(?:[#@][\w.-]+|\b[A-Z][\w.-]+(?:\s+[A-Z][\w.-]+){0,3})", description))
    seen = set()
    words = []
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip(" -|.,:;")
        key = normalized.casefold()
        if len(normalized) < 2 or key in seen:
            continue
        seen.add(key)
        words.append(normalized)
    return ", ".join(words)[:max_chars].rstrip(" ,")


def speech_gap_candidates(segments, audio, sample_rate, settings):
    """Return internal ASR gaps that still contain sustained acoustic energy."""
    ordered = sorted(
        (segment for segment in segments if segment.get("start") is not None and segment.get("end") is not None),
        key=lambda segment: float(segment["start"]),
    )
    if len(ordered) < 2 or not settings["repair_max_gaps"]:
        return []
    audio = np.asarray(audio, dtype=np.float32)
    floor = max(0.006, float(np.percentile(np.abs(audio), 35)) * 2.5)
    candidates = []
    for left, right in zip(ordered, ordered[1:]):
        start, end = float(left["end"]), float(right["start"])
        duration = end - start
        if not settings["repair_min_gap"] <= duration <= settings["repair_max_gap"]:
            continue
        chunk = audio[max(0, int(start * sample_rate)):min(len(audio), int(end * sample_rate))]
        frame = max(1, int(0.03 * sample_rate))
        rms = [
            float(np.sqrt(np.mean(part * part)))
            for offset in range(0, len(chunk), frame)
            if len(part := chunk[offset:offset + frame]) >= frame // 2
        ]
        voiced_ratio = sum(value >= floor for value in rms) / len(rms) if rms else 0.0
        if voiced_ratio >= 0.18:
            candidates.append({"start": start, "end": end, "voiced_ratio": round(voiced_ratio, 3)})
    candidates.sort(key=lambda item: (-item["voiced_ratio"], item["start"]))
    return sorted(candidates[: settings["repair_max_gaps"]], key=lambda item: item["start"])
