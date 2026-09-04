"""Deterministic text splitting helpers used before subtitle timestamping.

The functions in this module deliberately avoid LLM calls.  They keep every
non-whitespace character and prefer punctuation boundaries near equally sized
parts, which is sufficient for subtitle layout without asking a model to make
structural decisions.
"""

from __future__ import annotations

import math
import re
from typing import Callable


_PREFERRED_END = re.compile(r"[.!?;:,][\"')\]]*$")


def weighted_length(text: str) -> float:
    """Approximate visual width across Latin and common CJK scripts."""
    total = 0.0
    for char in str(text):
        code = ord(char)
        if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF:
            total += 1.75
        elif 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF:
            total += 1.5
        elif 0xFF01 <= code <= 0xFF5E:
            total += 1.75
        else:
            total += 1.0
    return total


def _character_parts(text: str, parts: int) -> list[str]:
    boundaries = [round(i * len(text) / parts) for i in range(parts + 1)]
    return [text[boundaries[i] : boundaries[i + 1]].strip() for i in range(parts)]


def split_balanced(
    text: str,
    parts: int,
    length_fn: Callable[[str], float] = weighted_length,
) -> list[str]:
    """Split text into balanced non-empty parts, preferring punctuation."""
    text = " ".join(str(text).split())
    if not text or parts <= 1:
        return [text]

    tokens = text.split(" ")
    if len(tokens) < parts:
        return [part for part in _character_parts(text, parts) if part]

    result: list[str] = []
    start = 0
    for part_index in range(parts - 1):
        remaining_parts = parts - part_index
        max_end = len(tokens) - (remaining_parts - 1)
        target = length_fn(" ".join(tokens[start:])) / remaining_parts
        candidates = range(start + 1, max_end + 1)

        def score(end: int) -> float:
            candidate = " ".join(tokens[start:end])
            distance = abs(length_fn(candidate) - target)
            if _PREFERRED_END.search(tokens[end - 1]):
                distance -= max(1.0, target * 0.12)
            return distance

        end = min(candidates, key=score)
        result.append(" ".join(tokens[start:end]).strip())
        start = end
    result.append(" ".join(tokens[start:]).strip())
    return [part for part in result if part]


def split_proportional(
    text: str,
    ratios: list[float],
    length_fn: Callable[[str], float] = weighted_length,
) -> list[str]:
    """Split text using source-part ratios while preferring natural boundaries."""
    text = " ".join(str(text).split())
    if not text or len(ratios) <= 1:
        return [text]
    tokens = text.split(" ")
    parts = len(ratios)
    if len(tokens) < parts:
        return [part for part in _character_parts(text, parts) if part]

    total_ratio = sum(ratios) or 1.0
    total_length = length_fn(text)
    result = []
    start = 0
    consumed_ratio = 0.0
    for part_index in range(parts - 1):
        consumed_ratio += ratios[part_index]
        desired_total = total_length * consumed_ratio / total_ratio
        max_end = len(tokens) - (parts - part_index - 1)
        candidates = range(start + 1, max_end + 1)

        def score(end: int) -> float:
            prefix = " ".join(tokens[:end])
            distance = abs(length_fn(prefix) - desired_total)
            if _PREFERRED_END.search(tokens[end - 1]):
                distance -= max(1.0, total_length / parts * 0.08)
            return distance

        end = min(candidates, key=score)
        result.append(" ".join(tokens[start:end]).strip())
        start = end
    result.append(" ".join(tokens[start:]).strip())
    return [part for part in result if part]


def split_for_subtitle_pair(
    source: str,
    translation: str,
    max_length: float,
    target_multiplier: float,
    max_parts: int = 8,
) -> tuple[list[str], list[str]]:
    """Split a source/translation pair into the same number of local parts."""
    source = " ".join(str(source).split())
    translation = " ".join(str(translation).split())
    required = max(
        1,
        math.ceil(weighted_length(source) / max_length),
        math.ceil(weighted_length(translation) * target_multiplier / max_length),
    )

    for parts in range(required, max_parts + 1):
        source_parts = split_balanced(source, parts)
        source_widths = [weighted_length(item) for item in source_parts]
        target_parts = split_proportional(translation, source_widths)
        if len(source_parts) != len(target_parts):
            continue
        if all(weighted_length(item) <= max_length for item in source_parts) and all(
            weighted_length(item) * target_multiplier <= max_length for item in target_parts
        ):
            return source_parts, target_parts

    raise ValueError(
        f"Unable to split subtitle locally within {max_parts} parts: "
        f"source={len(source)}, translation={len(translation)}"
    )


def normalized_content(text: str) -> str:
    """Return content identity used to prove that a split lost no characters."""
    return re.sub(r"\s+", "", str(text))
