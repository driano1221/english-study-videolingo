import os
import re
from difflib import SequenceMatcher


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def _normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text))
    text = re.sub(r"[–—]+", "-", text)
    return text.strip().casefold()


def _collapse_inline_repeats(text: str, max_repetitions: int = 2) -> str:
    """Limit obvious 3+ word stutters while preserving legitimate doubles."""
    if not text:
        return text
    words = str(text).split()
    output = []
    previous = None
    repeats = 0
    for word in words:
        identity = re.sub(r"[^\w]", "", word, flags=re.UNICODE).casefold()
        if identity and identity == previous:
            repeats += 1
        else:
            previous = identity
            repeats = 1
        if repeats <= max_repetitions:
            output.append(word)
    return " ".join(output).strip()


def _times_end_later(a_times: str, b_times: str) -> str:
    start = a_times.split(" --> ")[0]
    end = b_times.split(" --> ")[1]
    return f"{start} --> {end}"


def parse_srt(path: str):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    entries = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) >= 3:
            entries.append((lines[0], lines[1], "\n".join(lines[2:])))
    return entries


def write_srt(path: str, entries):
    with open(path, "w", encoding="utf-8") as handle:
        for index, (_, times, text) in enumerate(entries, 1):
            handle.write(f"{index}\n{times}\n{text}\n\n")


def clean_srt_entries(entries, similarity_threshold=0.995, max_gap_for_near=1):
    """Merge only effectively identical adjacent ASR entries.

    The older 0.82 similarity threshold could erase short sentences whose one
    changed word reversed the meaning.  Temporal data is not available here,
    so near matches are intentionally conservative.
    """
    del max_gap_for_near
    cleaned = []
    for entry in entries:
        index, times, text = entry
        text = _collapse_inline_repeats(text)
        if not text:
            continue
        if cleaned and similarity(_normalize(cleaned[-1][2]), _normalize(text)) >= similarity_threshold:
            previous = cleaned[-1]
            cleaned[-1] = (previous[0], _times_end_later(previous[1], times), previous[2])
        else:
            cleaned.append((index, times, text))
    return cleaned


def clean_text_lines(lines, similarity_threshold=0.995):
    """Remove only effectively identical consecutive sentence lines."""
    if not lines:
        return lines
    cleaned = []
    for line in lines:
        line = _collapse_inline_repeats(str(line).strip())
        if not line:
            continue
        if cleaned and similarity(_normalize(cleaned[-1]), _normalize(line)) >= similarity_threshold:
            continue
        cleaned.append(line)
    return cleaned


def clean_word_df(df, repeat_threshold=2):
    """Keep legitimate doubles and collapse only the third+ consecutive word."""
    if df is None or df.empty or not {"text", "start", "end"}.issubset(df.columns):
        return df

    result = df.copy().reset_index(drop=True)
    keep = []
    previous = None
    run_count = 0
    last_kept = None
    for position, row in result.iterrows():
        identity = re.sub(r"[^\w]", "", str(row["text"]), flags=re.UNICODE).casefold()
        if identity and identity == previous:
            run_count += 1
        else:
            previous = identity
            run_count = 1

        should_keep = not identity or run_count <= repeat_threshold
        keep.append(should_keep)
        if should_keep:
            last_kept = position
        elif last_kept is not None:
            result.at[last_kept, "end"] = max(result.at[last_kept, "end"], row["end"])
    return result[keep].reset_index(drop=True)


def clean_all_subtitles(output_dir="output"):
    """Clean aligned source/translation SRTs without semantic near-deduplication."""
    src_path = os.path.join(output_dir, "src.srt")
    trans_path = os.path.join(output_dir, "trans.srt")
    source = parse_srt(src_path)
    target = parse_srt(trans_path)
    if not source or not target:
        return

    pair_count = min(len(source), len(target))
    cleaned_source = []
    cleaned_target = []
    for src_entry, target_entry in zip(source[:pair_count], target[:pair_count]):
        src_text = _collapse_inline_repeats(src_entry[2])
        target_text = _collapse_inline_repeats(target_entry[2])
        is_exact_pair_duplicate = bool(cleaned_source) and (
            _normalize(cleaned_source[-1][2]) == _normalize(src_text)
            and _normalize(cleaned_target[-1][2]) == _normalize(target_text)
        )
        if is_exact_pair_duplicate:
            merged_times = _times_end_later(cleaned_source[-1][1], src_entry[1])
            cleaned_source[-1] = (
                cleaned_source[-1][0],
                merged_times,
                cleaned_source[-1][2],
            )
            cleaned_target[-1] = (
                cleaned_target[-1][0],
                merged_times,
                cleaned_target[-1][2],
            )
        else:
            cleaned_source.append((src_entry[0], src_entry[1], src_text))
            cleaned_target.append((target_entry[0], target_entry[1], target_text))

    write_srt(src_path, cleaned_source)
    write_srt(trans_path, cleaned_target)
    bilingual = [
        (src[0], src[1], f"{src[2]}\n{target[2]}")
        for src, target in zip(cleaned_source, cleaned_target)
    ]
    reverse = [
        (src[0], src[1], f"{target[2]}\n{src[2]}")
        for src, target in zip(cleaned_source, cleaned_target)
    ]
    write_srt(os.path.join(output_dir, "src_trans.srt"), bilingual)
    write_srt(os.path.join(output_dir, "trans_src.srt"), reverse)
    print(f"Conservative subtitle cleanup: {pair_count} -> {len(cleaned_source)} entries")
