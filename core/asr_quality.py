"""Fail closed when an ASR transcript contains obvious hallucination loops."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def _word(value: object) -> str:
    return re.sub(r"[^\w']", "", str(value), flags=re.UNICODE).casefold()


def repeated_phrase_loops(words: list[str], minimum_repeats: int = 6) -> list[dict]:
    """Find consecutive repeated phrases of two to six words."""
    clean = [word for word in (_word(value) for value in words) if word]
    found = []
    occupied_until = -1
    for start in range(len(clean)):
        if start < occupied_until:
            continue
        best = None
        for width in range(2, 7):
            phrase = clean[start : start + width]
            if len(phrase) < width:
                continue
            repeats = 1
            while clean[start + repeats * width : start + (repeats + 1) * width] == phrase:
                repeats += 1
            if repeats >= minimum_repeats and (best is None or repeats * width > best[0]):
                best = (repeats * width, width, repeats, phrase)
        if best:
            span, _, repeats, phrase = best
            found.append(
                {"start_word": start, "phrase": " ".join(phrase), "repeats": repeats, "words": span}
            )
            occupied_until = start + span
    return found


def validate_asr_transcription(path: str | Path) -> dict:
    """Reject obvious ASR corruption before any translation API call."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("ASR validation failed: transcription artifact is missing")
    frame = pd.read_excel(path)
    if frame.empty or "text" not in frame:
        raise RuntimeError("ASR validation failed: transcription has no words")
    loops = repeated_phrase_loops(frame["text"].tolist())
    if loops:
        examples = ", ".join(
            f"'{item['phrase']}' x{item['repeats']}" for item in loops[:3]
        )
        raise RuntimeError(
            "ASR quality validation stopped the job before translation: "
            f"repeated hallucination loop(s) detected ({examples})."
        )
    return {"words": len(frame), "repeated_phrase_loops": 0}
