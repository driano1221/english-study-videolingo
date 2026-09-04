import json

import pandas as pd
from rich.console import Console

from core._4_1_summarize import search_things_to_note_in_prompt
from core.translate_lines import translate_lines
from core.utils import check_cancel, check_file_exists, load_key
from core.utils.models import _3_2_SPLIT_BY_MEANING, _4_1_TERMINOLOGY, _4_2_TRANSLATION


console = Console()


def _setting(key, default):
    try:
        return load_key(key)
    except (KeyError, TypeError):
        return default


def split_chunks_by_chars(chunk_size, max_i):
    """Build large, ordered translation batches without splitting a subtitle."""
    with open(_3_2_SPLIT_BY_MEANING, "r", encoding="utf-8") as handle:
        sentences = [line.strip() for line in handle if line.strip()]

    chunks = []
    current = []
    current_chars = 0
    for sentence in sentences:
        added = len(sentence) + (1 if current else 0)
        if current and (current_chars + added > chunk_size or len(current) >= max_i):
            chunks.append("\n".join(current))
            current = []
            current_chars = 0
        current.append(sentence)
        current_chars += len(sentence) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append("\n".join(current))
    return chunks


def get_previous_content(chunks, chunk_index):
    return [] if chunk_index == 0 else chunks[chunk_index - 1].splitlines()[-3:]


def get_after_content(chunks, chunk_index):
    return [] if chunk_index == len(chunks) - 1 else chunks[chunk_index + 1].splitlines()[:2]


def translate_chunk(chunk, chunks, theme_prompt, index):
    translation, original = translate_lines(
        chunk,
        get_previous_content(chunks, index),
        get_after_content(chunks, index),
        search_things_to_note_in_prompt(chunk),
        theme_prompt,
        index,
    )
    return original.splitlines(), translation.splitlines()


@check_file_exists(_4_2_TRANSLATION)
def translate_all():
    chunk_size = int(_setting("translation.batch_chars", 6500))
    max_lines = int(_setting("translation.batch_max_lines", 120))
    chunks = split_chunks_by_chars(chunk_size=chunk_size, max_i=max_lines)
    with open(_4_1_TERMINOLOGY, "r", encoding="utf-8") as handle:
        theme_prompt = json.load(handle).get("theme", "")

    console.print(
        f"[bold green]Translating {sum(len(c.splitlines()) for c in chunks)} lines "
        f"in {len(chunks)} batch(es)...[/bold green]"
    )
    source_lines = []
    translated_lines = []
    for index, chunk in enumerate(chunks):
        check_cancel()
        source, translated = translate_chunk(chunk, chunks, theme_prompt, index)
        if len(source) != len(translated):
            raise ValueError(
                f"Translation batch {index + 1} changed line count: "
                f"{len(source)} -> {len(translated)}"
            )
        source_lines.extend(source)
        translated_lines.extend(translated)

    pd.DataFrame(
        {"Source": source_lines, "Translation": translated_lines}
    ).to_excel(_4_2_TRANSLATION, index=False)
    console.print(
        f"[bold green]Translation saved: {len(source_lines)} lines, "
        f"{len(chunks)} paid translation call(s), no subtitle trimming calls.[/bold green]"
    )


if __name__ == "__main__":
    translate_all()
