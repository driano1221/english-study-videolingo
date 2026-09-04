# -*- coding: utf-8 -*-
"""Regenerate final video after fixing subtitle alignment issues."""
import shutil
import datetime

from _bootstrap import configure_runtime

configure_runtime()

import pandas as pd
from difflib import SequenceMatcher
from core.utils.models import _5_SPLIT_SUB, _5_REMERGED, _OUTPUT_DIR
from core import _6_gen_sub, _7_sub_into_vid


def similarity(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _is_empty(val):
    if val is None:
        return True
    if isinstance(val, float) and pd.isna(val):
        return True
    return str(val).strip() == '' or str(val).strip().lower() == 'nan'


def remove_duplicate_rows(df, threshold=0.85):
    """Remove rows with empty translations and consecutive near-duplicates."""
    if df.empty:
        return df
    seen_sources = []
    keep = []
    for i in range(len(df)):
        src_curr = str(df.iloc[i]['Source']).strip()
        trans_curr = df.iloc[i]['Translation']
        trans_empty = _is_empty(trans_curr)

        # Drop rows with no translation (these are alignment errors)
        if trans_empty:
            keep.append(False)
            continue

        # Drop if this source is very similar to any recent source we've kept
        is_dup = False
        for src_prev in seen_sources[-10:]:
            if similarity(src_prev, src_curr) >= threshold:
                is_dup = True
                break

        if is_dup:
            keep.append(False)
        else:
            keep.append(True)
            seen_sources.append(src_curr)

    return df[keep].reset_index(drop=True)


def main():
    print("Loading subtitle data...")
    df_sub = pd.read_excel(_5_SPLIT_SUB)
    df_remerged = pd.read_excel(_5_REMERGED)

    original_len = len(df_sub)
    df_sub = remove_duplicate_rows(df_sub)
    removed = original_len - len(df_sub)
    print("Removed {} duplicate rows from {}".format(removed, _5_SPLIT_SUB))

    # Also trim remerged file to match
    min_len = min(len(df_sub), len(df_remerged))
    df_remerged = df_remerged.iloc[:min_len].reset_index(drop=True)
    if len(df_sub) > len(df_remerged):
        # Pad remerged with empty if needed
        pad = pd.DataFrame({'Source': [''] * (len(df_sub) - len(df_remerged)),
                            'Translation': [''] * (len(df_sub) - len(df_remerged))})
        df_remerged = pd.concat([df_remerged, pad], ignore_index=True)

    df_sub.to_excel(_5_SPLIT_SUB, index=False)
    df_remerged.to_excel(_5_REMERGED, index=False)

    print("Regenerating subtitles...")
    _6_gen_sub.align_timestamp_main()

    print("Fixing stutter artifacts...")
    import fix_srt_artifacts
    fix_srt_artifacts.fix_all_srts()

    print("Burning subtitles into video...")
    _7_sub_into_vid.merge_subtitles_to_video()

    output_file = os.path.join(_OUTPUT_DIR, "output_sub.mp4")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    final_file = os.path.join(project_root, "Is_spider_web_really_stronger_than_steel_bilingual_{}.mp4".format(timestamp))
    if os.path.exists(output_file):
        shutil.copy2(output_file, final_file)
        print("\nCopied final video to: {}".format(final_file))

    print("\nDone!")


if __name__ == "__main__":
    main()
