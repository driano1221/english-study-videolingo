from typing import List

import pandas as pd
from rich.console import Console

from core.local_text import normalized_content, split_for_subtitle_pair, weighted_length
from core.utils import check_file_exists, load_key
from core.utils.models import _4_2_TRANSLATION, _5_REMERGED, _5_SPLIT_SUB


console = Console()


def calc_len(text: str) -> float:
    """Backward-compatible alias for visual subtitle width."""
    return weighted_length(text)


def split_align_subs(src_lines: List[str], tr_lines: List[str]):
    """Split source and target locally into matching, balanced subtitle parts."""
    if len(src_lines) != len(tr_lines):
        raise ValueError(f"Source/translation length mismatch: {len(src_lines)} != {len(tr_lines)}")

    subtitle = load_key("subtitle")
    max_length = float(subtitle["max_length"])
    target_multiplier = float(subtitle["target_multiplier"])
    split_source = []
    split_target = []
    remerged_target = [str(item) for item in tr_lines]
    split_count = 0

    for source, target in zip(src_lines, tr_lines):
        source = " ".join(str(source).split())
        target = " ".join(str(target).split())
        source_parts, target_parts = split_for_subtitle_pair(
            source,
            target,
            max_length=max_length,
            target_multiplier=target_multiplier,
        )
        if normalized_content("".join(source_parts)) != normalized_content(source):
            raise ValueError("Local source split lost content")
        if normalized_content("".join(target_parts)) != normalized_content(target):
            raise ValueError("Local translation split lost content")
        if len(source_parts) > 1:
            split_count += 1
        split_source.extend(source_parts)
        split_target.extend(target_parts)

    console.print(
        f"[green]Local subtitle alignment complete: {split_count} long pairs split, "
        f"{len(split_source)} output lines, no LLM calls.[/green]"
    )
    return split_source, split_target, remerged_target


@check_file_exists(_5_SPLIT_SUB)
def split_for_sub_main():
    frame = pd.read_excel(_4_2_TRANSLATION)
    source = frame["Source"].fillna("").astype(str).tolist()
    translation = frame["Translation"].fillna("").astype(str).tolist()
    split_source, split_translation, remerged = split_align_subs(source, translation)

    pd.DataFrame(
        {"Source": split_source, "Translation": split_translation}
    ).to_excel(_5_SPLIT_SUB, index=False)
    pd.DataFrame(
        {"Source": source, "Translation": remerged}
    ).to_excel(_5_REMERGED, index=False)


if __name__ == "__main__":
    split_for_sub_main()
