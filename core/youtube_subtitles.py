"""Prepare the best available YouTube captions before falling back to ASR."""

from __future__ import annotations

import html
import json
import math
import re
import time
from pathlib import Path

from rich import print as rprint

from core._1_ytdlp import get_js_runtimes, get_ytdlp
from core.local_text import split_balanced, split_proportional, weighted_length
from core.utils import load_key


TARGET_LANGUAGE_CODES = {
    "Português brasileiro": {"manual": ["pt-BR", "pt"], "auto": ["pt", "pt-BR"]},
    "Español": {"manual": ["es"], "auto": ["es"]},
    "Français": {"manual": ["fr"], "auto": ["fr"]},
    "Deutsch": {"manual": ["de"], "auto": ["de"]},
    "Italiano": {"manual": ["it"], "auto": ["it"]},
    "Русский": {"manual": ["ru"], "auto": ["ru"]},
    "中文（简体）": {"manual": ["zh-Hans", "zh-CN"], "auto": ["zh-Hans"]},
    "日本語": {"manual": ["ja"], "auto": ["ja"]},
}

SOURCE_LANGUAGE_CODES = ["en", "en-US", "en-GB", "en-orig"]
AUTO_SOURCE_LANGUAGE_CODES = ["en-orig", "en", "en-US", "en-GB"]
READABILITY_VERSION = 2
_SENTENCE_BOUNDARY = re.compile(r"[.!?…][\"'”’)]*(?=\s|$)")
_STAGE_DIRECTION = re.compile(r"^\[[^]]+\]$")


def _seconds(value: str) -> float:
    hours, minutes, rest = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def _timestamp(value: float) -> str:
    milliseconds = max(0, round(value * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def parse_srt(path: Path) -> list[dict]:
    """Parse non-empty SRT cues while normalizing YouTube markup."""
    raw = path.read_text(encoding="utf-8-sig").strip()
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", raw):
        lines = block.splitlines()
        if len(lines) < 2 or " --> " not in lines[1]:
            continue
        start, end = lines[1].split(" --> ", 1)
        text = " ".join(lines[2:]).strip()
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
        text = " ".join(text.split())
        if text:
            cues.append({"start": _seconds(start), "end": _seconds(end), "text": text})
    return cues


def normalize_automatic_cues(cues: list[dict]) -> list[dict]:
    """Convert YouTube's rolling automatic captions into non-overlapping cues.

    YouTube replaces a caption window after the next phrase starts. SRT stores
    the longer on-screen lifetime, which makes burned captions stack. Ending a
    cue at the next content start reproduces the replacement behavior.
    """
    normalized = []
    for index, cue in enumerate(cues):
        start = float(cue["start"])
        end = float(cue["end"])
        if index + 1 < len(cues):
            next_start = float(cues[index + 1]["start"])
            if next_start > start:
                end = min(end, next_start)
        if end <= start:
            end = start + 0.08
        normalized.append({"start": start, "end": end, "text": cue["text"]})
    return normalized


def align_automatic_tracks(
    source: list[dict], target: list[dict]
) -> tuple[list[dict], list[str]]:
    """Pair differently grouped automatic tracks using their shared timeline.

    YouTube may merge a few translated windows, so cue counts can differ even
    though both tracks cover the same speech. Every source cue is assigned once
    to the nearest target time window, then adjacent source fragments are joined.
    """
    if not source or not target:
        raise ValueError("Automatic subtitle tracks are empty")
    groups: list[list[dict]] = [[] for _ in target]
    target_index = 0
    for cue in source:
        midpoint = (cue["start"] + cue["end"]) / 2
        while (
            target_index + 1 < len(target)
            and target[target_index + 1]["start"] <= midpoint
        ):
            target_index += 1
        candidates = {target_index}
        if target_index + 1 < len(target):
            candidates.add(target_index + 1)
        if target_index > 0:
            candidates.add(target_index - 1)

        def distance(index: int) -> float:
            cue_target = target[index]
            if cue_target["start"] <= midpoint <= cue_target["end"]:
                return 0.0
            return min(
                abs(midpoint - cue_target["start"]),
                abs(midpoint - cue_target["end"]),
            )

        best = min(candidates, key=distance)
        groups[best].append(cue)

    if any(not group for group in groups):
        raise ValueError("Automatic subtitle timelines could not be paired safely")
    aligned_source = [
        {
            "start": target_cue["start"],
            "end": target_cue["end"],
            "text": " ".join(cue["text"] for cue in group),
        }
        for target_cue, group in zip(target, groups)
    ]
    return aligned_source, [cue["text"] for cue in target]


def subtitle_gap_stats(cues: list[dict]) -> dict:
    gaps = [
        max(0.0, following["start"] - current["end"])
        for current, following in zip(cues, cues[1:])
    ]
    positive = [gap for gap in gaps if gap > 0.001]
    overlaps = [
        current["end"] - following["start"]
        for current, following in zip(cues, cues[1:])
        if current["end"] - following["start"] > 0.001
    ]
    return {
        "entries": len(cues),
        "internal_gap_count": len(positive),
        "internal_gap_seconds": round(sum(positive), 3),
        "max_internal_gap_seconds": round(max(positive, default=0.0), 3),
        "overlap_count": len(overlaps),
        "max_overlap_seconds": round(max(overlaps, default=0.0), 3),
    }


def _join_caption_text(left: str, right: str) -> str:
    text = re.sub(r"\s+", " ", f"{left.strip()} {right.strip()}").strip()
    text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    text = re.sub(r"([¿¡])\s+", r"\1", text)
    return text


def _time_parts(start: float, end: float, texts: list[str]) -> list[tuple[float, float]]:
    widths = [max(1.0, weighted_length(text)) for text in texts]
    total = sum(widths)
    cursor = float(start)
    result = []
    for index, width in enumerate(widths):
        part_end = float(end) if index + 1 == len(widths) else cursor + (end - start) * width / total
        result.append((cursor, part_end))
        cursor = part_end
    return result


def _timed_words(cue: dict) -> list[dict]:
    existing = cue.get("_word_times")
    if existing:
        return [dict(word) for word in existing]
    words = str(cue["text"]).split()
    if not words:
        return []
    duration = float(cue["end"]) - float(cue["start"])
    return [
        {
            "text": word,
            "start": float(cue["start"]) + duration * index / len(words),
            "end": float(cue["start"]) + duration * (index + 1) / len(words),
        }
        for index, word in enumerate(words)
    ]


def _word_time_parts(cue: dict, texts: list[str]) -> tuple[list[tuple[float, float]], list[list[dict]]]:
    words = _timed_words(cue)
    counts = [len(text.split()) for text in texts]
    if words and sum(counts) == len(words):
        groups = []
        cursor = 0
        for count in counts:
            groups.append(words[cursor:cursor + count])
            cursor += count
        return [
            (group[0]["start"], group[-1]["end"])
            for group in groups
        ], groups
    return _time_parts(float(cue["start"]), float(cue["end"]), texts), [[] for _ in texts]


def _split_completed_sentences(text: str) -> tuple[list[str], str]:
    completed = []
    cursor = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        part = text[cursor:match.end()].strip()
        if part:
            completed.append(part)
        cursor = match.end()
    return completed, text[cursor:].strip()


def _sentence_pairs(
    source: list[dict], target_texts: list[str], max_gap: float, max_window: float = 14.0
) -> list[tuple[dict, str]]:
    """Recover sentence boundaries from the punctuated translation."""
    result: list[tuple[dict, str]] = []
    buffer_source = ""
    buffer_target = ""
    buffer_start = 0.0
    buffer_end = 0.0
    buffer_word_times: list[dict] = []

    def flush() -> None:
        nonlocal buffer_source, buffer_target, buffer_word_times
        if buffer_source and buffer_target:
            result.append(({
                "start": buffer_start,
                "end": buffer_end,
                "text": buffer_source,
                "_word_times": buffer_word_times,
            }, buffer_target))
        buffer_source = ""
        buffer_target = ""
        buffer_word_times = []

    for cue, target_raw in zip(source, target_texts):
        source_text = str(cue["text"]).strip()
        target_text = str(target_raw).strip()
        if _STAGE_DIRECTION.fullmatch(source_text) or _STAGE_DIRECTION.fullmatch(target_text):
            flush()
            result.append((dict(cue), target_text))
            continue
        if buffer_source and float(cue["start"]) - buffer_end > max_gap:
            flush()
        elif buffer_source and float(cue["end"]) - buffer_start > max_window:
            # Some automatic translations contain minutes without sentence
            # punctuation. Bound the buffer, then split that passage locally.
            flush()
        if not buffer_source:
            buffer_start = float(cue["start"])
        buffer_end = float(cue["end"])
        buffer_source = _join_caption_text(buffer_source, source_text)
        buffer_target = _join_caption_text(buffer_target, target_text)
        buffer_word_times.extend(_timed_words(cue))

        completed, remainder = _split_completed_sentences(buffer_target)
        if not completed:
            continue
        target_parts = completed + ([remainder] if remainder else [])
        ratios = [weighted_length(part) for part in target_parts]
        source_parts = split_proportional(buffer_source, ratios)
        if len(source_parts) != len(target_parts):
            continue
        buffered_cue = {
            "start": buffer_start,
            "end": buffer_end,
            "text": buffer_source,
            "_word_times": buffer_word_times,
        }
        times, word_groups = _word_time_parts(buffered_cue, source_parts)
        for index in range(len(completed)):
            result.append(({
                "start": times[index][0],
                "end": times[index][1],
                "text": source_parts[index],
                "_word_times": word_groups[index],
            }, completed[index]))
        if remainder:
            buffer_source = source_parts[-1]
            buffer_target = remainder
            buffer_start = times[-1][0]
            buffer_word_times = word_groups[-1]
        else:
            buffer_source = ""
            buffer_target = ""
            buffer_word_times = []

    flush()
    return result


def _split_long_pair(
    cue: dict,
    target: str,
    *,
    max_duration: float,
    max_source_chars: int,
    max_target_chars: int,
) -> list[tuple[dict, str]]:
    duration = float(cue["end"]) - float(cue["start"])
    parts = max(
        1,
        math.ceil(duration / max_duration),
        math.ceil(weighted_length(cue["text"]) / max_source_chars),
        math.ceil(weighted_length(target) / max_target_chars),
    )
    if parts == 1 or _STAGE_DIRECTION.fullmatch(str(cue["text"]).strip()):
        return [(dict(cue), target)]
    target_parts = split_balanced(target, parts)
    source_parts = split_proportional(
        cue["text"], [weighted_length(part) for part in target_parts]
    )
    if len(source_parts) != len(target_parts):
        return [(dict(cue), target)]
    times, word_groups = _word_time_parts(cue, source_parts)
    return [
        ({
            "start": start,
            "end": end,
            "text": source_text,
            "_word_times": words,
        }, target_text)
        for source_text, target_text, (start, end), words in zip(
            source_parts, target_parts, times, word_groups
        )
    ]


def _merge_tiny_pairs(
    pairs: list[tuple[dict, str]],
    *,
    max_source_chars: int,
    max_target_chars: int,
    min_duration: float = 1.0,
) -> list[tuple[dict, str]]:
    merged: list[tuple[dict, str]] = []
    for cue, target in pairs:
        duration = float(cue["end"]) - float(cue["start"])
        if duration < min_duration and merged:
            previous, previous_target = merged[-1]
            combined_source = _join_caption_text(previous["text"], cue["text"])
            combined_target = _join_caption_text(previous_target, target)
            if (
                float(cue["start"]) - float(previous["end"]) <= 0.05
                and not _STAGE_DIRECTION.fullmatch(str(previous["text"]).strip())
                and len(combined_source) <= max_source_chars + 20
                and len(combined_target) <= max_target_chars + 20
            ):
                previous["end"] = cue["end"]
                previous["text"] = combined_source
                previous["_word_times"] = _timed_words(previous) + _timed_words(cue)
                merged[-1] = (previous, combined_target)
                continue
        merged.append((dict(cue), target))
    result: list[tuple[dict, str]] = []
    index = 0
    while index < len(merged):
        cue, target = merged[index]
        duration = float(cue["end"]) - float(cue["start"])
        if duration < min_duration and index + 1 < len(merged):
            following, following_target = merged[index + 1]
            combined_source = _join_caption_text(cue["text"], following["text"])
            combined_target = _join_caption_text(target, following_target)
            if (
                float(following["start"]) - float(cue["end"]) <= 0.05
                and not _STAGE_DIRECTION.fullmatch(str(following["text"]).strip())
                and len(combined_source) <= max_source_chars + 20
                and len(combined_target) <= max_target_chars + 20
            ):
                merged[index + 1] = ({
                    "start": cue["start"],
                    "end": following["end"],
                    "text": combined_source,
                    "_word_times": _timed_words(cue) + _timed_words(following),
                }, combined_target)
                index += 1
                continue
        result.append((cue, target))
        index += 1
    return result


def group_automatic_source_for_translation(
    source: list[dict], *, max_duration: float = 6.0, max_chars: int = 84, max_gap: float = 0.35
) -> list[dict]:
    """Give the translator phrase-sized inputs instead of tiny rolling fragments."""
    if not source:
        return []
    grouped = []
    current = dict(source[0])
    for cue in source[1:]:
        combined = _join_caption_text(current["text"], cue["text"])
        can_join = (
            not _STAGE_DIRECTION.fullmatch(str(current["text"]).strip())
            and not _STAGE_DIRECTION.fullmatch(str(cue["text"]).strip())
            and float(cue["start"]) - float(current["end"]) <= max_gap
            and float(cue["end"]) - float(current["start"]) <= max_duration
            and len(combined) <= max_chars
        )
        if can_join:
            current["end"] = cue["end"]
            current["text"] = combined
        else:
            grouped.append(current)
            current = dict(cue)
    grouped.append(current)
    return grouped


def regroup_automatic_caption_pairs(
    source: list[dict],
    target_texts: list[str],
    *,
    max_duration: float = 6.0,
    max_source_chars: int = 84,
    max_target_chars: int = 94,
    max_gap: float = 0.35,
) -> tuple[list[dict], list[str]]:
    """Rebuild automatic fragments around sentences, then split long clauses."""
    if len(source) != len(target_texts):
        raise ValueError("Source and target caption counts differ before regrouping")
    if not source:
        return [], []

    sentences = _sentence_pairs(source, target_texts, max_gap)
    final = []
    for cue, target in sentences:
        final.extend(
            _split_long_pair(
                cue,
                target,
                max_duration=max_duration,
                max_source_chars=max_source_chars,
                max_target_chars=max_target_chars,
            )
        )
    final = _merge_tiny_pairs(
        final,
        max_source_chars=max_source_chars,
        max_target_chars=max_target_chars,
    )
    return [cue for cue, _ in final], [target for _, target in final]


def load_prepared_youtube_subtitles(output_dir: str | Path = "output") -> dict | None:
    """Reuse a validated YouTube subtitle pair without network or API calls."""
    output_dir = Path(output_dir)
    source_path = output_dir / "src.srt"
    target_path = output_dir / "trans.srt"
    audit_path = output_dir / "log" / "subtitle_source.json"
    if not all(path.is_file() and path.stat().st_size > 0 for path in (source_path, target_path, audit_path)):
        return None
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        source = parse_srt(source_path)
        target = parse_srt(target_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not str(audit.get("source", "")).startswith("youtube_"):
        return None
    if not source or len(source) != len(target):
        return None
    if any(not cue["text"].strip() for cue in source + target):
        return None
    if int(audit.get("entries", 0) or 0) != len(source):
        return None
    if (
        str(audit.get("source", "")).startswith("youtube_automatic")
        and int(audit.get("readability_version", 0) or 0) < READABILITY_VERSION
    ):
        return _write_subtitle_pair(
            source,
            [cue["text"] for cue in target],
            output_dir,
            str(audit["source"]),
        )
    return audit


def _render_srt(cues: list[dict]) -> str:
    blocks = []
    for index, cue in enumerate(cues, 1):
        blocks.append(
            f"{index}\n{_timestamp(cue['start'])} --> {_timestamp(cue['end'])}\n{cue['text']}"
        )
    return "\n\n".join(blocks) + "\n"


def _write_subtitle_pair(
    source: list[dict],
    target_texts: list[str],
    output_dir: Path,
    source_kind: str,
) -> dict:
    if not source or len(source) != len(target_texts):
        raise ValueError(
            f"Subtitle tracks cannot be paired safely: source={len(source)}, "
            f"target={len(target_texts)}"
        )
    original_entries = len(source)
    if source_kind.startswith("youtube_automatic"):
        source, target_texts = regroup_automatic_caption_pairs(source, target_texts)
    paired_target = [
        {"start": cue["start"], "end": cue["end"], "text": str(text).strip()}
        for cue, text in zip(source, target_texts)
    ]
    if any(not cue["text"] for cue in paired_target):
        raise ValueError("A translated YouTube subtitle is empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "src.srt").write_text(_render_srt(source), encoding="utf-8")
    (output_dir / "trans.srt").write_text(_render_srt(paired_target), encoding="utf-8")
    combined_source = [
        {**src, "text": f"{src['text']}\n{tgt['text']}"}
        for src, tgt in zip(source, paired_target)
    ]
    combined_target = [
        {**src, "text": f"{tgt['text']}\n{src['text']}"}
        for src, tgt in zip(source, paired_target)
    ]
    (output_dir / "src_trans.srt").write_text(_render_srt(combined_source), encoding="utf-8")
    (output_dir / "trans_src.srt").write_text(_render_srt(combined_target), encoding="utf-8")

    stats = subtitle_gap_stats(source)
    stats.update(
        {
            "source": source_kind,
            "target_entries": len(target_texts),
            "original_entries": original_entries,
            "readability_version": (
                READABILITY_VERSION if source_kind.startswith("youtube_automatic") else 0
            ),
        }
    )
    log_dir = output_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "subtitle_source.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stats


def write_paired_subtitles(source_path: Path, target_path: Path, output_dir: Path) -> dict:
    """Pair manual source timing with translated cues by non-empty cue order."""
    source = parse_srt(source_path)
    target = parse_srt(target_path)
    return _write_subtitle_pair(
        source,
        [cue["text"] for cue in target],
        output_dir,
        "youtube_manual_subtitles",
    )


def _first_available(available: dict, candidates: list[str]) -> str | None:
    return next((code for code in candidates if code in available), None)


def _download_track(
    url: str,
    output_dir: Path,
    language_code: str,
    automatic: bool,
    label: str,
    attempts: int = 1,
) -> Path | None:
    prefix = output_dir / f".youtube_{label}"
    options = {
        "skip_download": True,
        "writesubtitles": not automatic,
        "writeautomaticsub": automatic,
        "subtitleslangs": [language_code],
        "subtitlesformat": "srt",
        "outtmpl": str(prefix) + ".%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
    }
    js_runtimes = get_js_runtimes()
    if js_runtimes:
        options["js_runtimes"] = js_runtimes
    cookies_path = load_key("youtube.cookies_path")
    if cookies_path and Path(cookies_path).is_file():
        options["cookiefile"] = str(cookies_path)
    path = output_dir / f".youtube_{label}.{language_code}.srt"
    for attempt in range(1, attempts + 1):
        try:
            YoutubeDL = get_ytdlp()
            with YoutubeDL(options) as downloader:
                downloader.download([url])
            if path.is_file() and path.stat().st_size > 0:
                return path
        except Exception as exc:
            rprint(
                f"[yellow]YouTube caption track {language_code} attempt "
                f"{attempt}/{attempts} failed: {exc}[/yellow]"
            )
        if attempt < attempts:
            time.sleep(2 * attempt)
    return None


def _translate_source_cues(source: list[dict]) -> list[str]:
    """Translate caption cues in large ordered batches with API accounting."""
    from core.translate_lines import translate_lines

    # Smaller direct-caption batches keep JSON comfortably inside the model's
    # output limit. A failed batch is recursively divided instead of restarting
    # or accepting an incomplete response.
    max_chars = min(int(load_key("translation.batch_chars")), 2600)
    max_lines = min(int(load_key("translation.batch_max_lines")), 24)
    batches: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for cue in source:
        text = cue["text"].replace("\n", " ").strip()
        added = len(text) + (1 if current else 0)
        if current and (current_chars + added > max_chars or len(current) >= max_lines):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(text)
        current_chars += len(text) + (1 if len(current) > 1 else 0)
    if current:
        batches.append(current)

    def translate_batch(
        batch: list[str], previous: list[str], following: list[str], label: str
    ) -> list[str]:
        try:
            result, original = translate_lines(
                "\n".join(batch), previous, following, "", "", 0,
                validation_retries_override=0,
                temperature_override=0.0,
            )
            originals = original.splitlines()
            translations = result.splitlines()
            if len(originals) != len(batch) or len(translations) != len(batch):
                raise ValueError(
                    f"YouTube caption translation changed line count in batch {label}: "
                    f"{len(batch)} -> {len(translations)}"
                )
            return translations
        except ValueError:
            if len(batch) <= 10:
                raise
            midpoint = len(batch) // 2
            rprint(
                f"[yellow]Translation batch {label} was incomplete; retrying as "
                f"{midpoint} + {len(batch) - midpoint} cues.[/yellow]"
            )
            left = translate_batch(batch[:midpoint], previous, batch[midpoint : midpoint + 2], label + "a")
            right = translate_batch(batch[midpoint:], batch[max(0, midpoint - 3) : midpoint], following, label + "b")
            return left + right

    translated: list[str] = []
    rprint(
        f"[bold green]Translating {len(source)} YouTube caption cues in "
        f"{len(batches)} ordered batch(es)...[/bold green]"
    )
    for index, batch in enumerate(batches):
        previous = batches[index - 1][-3:] if index else []
        following = batches[index + 1][:2] if index + 1 < len(batches) else []
        translated.extend(translate_batch(batch, previous, following, str(index + 1)))
    return translated


def _caption_info(url: str) -> tuple[dict, dict]:
    options = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True}
    js_runtimes = get_js_runtimes()
    if js_runtimes:
        options["js_runtimes"] = js_runtimes
    cookies_path = load_key("youtube.cookies_path")
    if cookies_path and Path(cookies_path).is_file():
        options["cookiefile"] = str(cookies_path)
    YoutubeDL = get_ytdlp()
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
    return info.get("subtitles") or {}, info.get("automatic_captions") or {}


def try_prepare_youtube_subtitles(
    url: str,
    target_language: str,
    output_dir: str | Path = "output",
) -> dict | None:
    """Use manual or automatic YouTube captions, translating source if needed."""
    language_codes = TARGET_LANGUAGE_CODES.get(target_language)
    if not language_codes:
        return None
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        manual, automatic = _caption_info(url)
    except Exception as exc:
        rprint(f"[yellow]Could not inspect YouTube captions: {exc}[/yellow]")
        return None

    source_code = _first_available(manual, SOURCE_LANGUAGE_CODES)
    source_automatic = False
    source_kind = "youtube_manual_subtitles"
    if not source_code:
        source_code = _first_available(automatic, AUTO_SOURCE_LANGUAGE_CODES)
        source_automatic = bool(source_code)
        source_kind = "youtube_automatic_subtitles"
    if not source_code:
        rprint("[yellow]No English YouTube caption track found; using ASR fallback.[/yellow]")
        return None

    source_path = _download_track(url, output_dir, source_code, source_automatic, "source")
    if not source_path:
        return None
    source = parse_srt(source_path)
    if source_automatic:
        source = normalize_automatic_cues(source)
    if not source:
        return None

    target_pool = automatic if source_automatic else manual
    target_candidates = language_codes["auto" if source_automatic else "manual"]
    target_code = _first_available(target_pool, target_candidates)
    target_texts = None
    if target_code:
        target_path = _download_track(
            url, output_dir, target_code, source_automatic, "target", attempts=3
        )
        if target_path:
            target = parse_srt(target_path)
            if source_automatic:
                target = normalize_automatic_cues(target)
            if len(target) == len(source):
                target_texts = [cue["text"] for cue in target]
            elif source_automatic:
                source, target_texts = align_automatic_tracks(source, target)
                rprint(
                    f"[green]Aligned differently grouped YouTube tracks on their timeline: "
                    f"{len(source)} final cues.[/green]"
                )
            else:
                rprint(
                    f"[yellow]YouTube target track count differs "
                    f"({len(source)} vs {len(target)}); translating the reliable source track.[/yellow]"
                )

    if target_texts is None:
        if source_automatic:
            source = group_automatic_source_for_translation(source)
        target_texts = _translate_source_cues(source)
        source_kind += "_api_translated"

    stats = _write_subtitle_pair(source, target_texts, output_dir, source_kind)
    api_note = "translation API used" if source_kind.endswith("_api_translated") else "no API needed"
    rprint(
        "[bold green]Using complete YouTube captions: "
        f"{stats['entries']} paired cues, {stats['internal_gap_seconds']:.3f}s "
        f"of internal gaps, {api_note}.[/bold green]"
    )
    return stats
