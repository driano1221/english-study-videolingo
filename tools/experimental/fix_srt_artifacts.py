# -*- coding: utf-8 -*-
"""Fix stutter artifacts left in the source subtitles after cleaning.

VideoLingo sometimes merges stutter fragments with the following sentence,
producing source lines like:
    "what are called knock- The second is a cutting protein."
    "proteins for fibers, coatings, coating, But now"

The translation is usually clean, so we use it as a hint to repair the source.
"""
import os
import re
from difflib import SequenceMatcher

from _bootstrap import configure_runtime

configure_runtime()

from core.clean_subtitles import parse_srt, write_srt

OUTPUT_DIR = "output"
SRC_SRT = os.path.join(OUTPUT_DIR, "src.srt")
TRANS_SRT = os.path.join(OUTPUT_DIR, "trans.srt")
SRC_TRANS_SRT = os.path.join(OUTPUT_DIR, "src_trans.srt")
TRANS_SRC_SRT = os.path.join(OUTPUT_DIR, "trans_src.srt")


def _similarity(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def split_sentences(text):
    """Rough sentence split that keeps the delimiter."""
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]


def count_sentences(text):
    return len(split_sentences(text))


def fix_truncated_word(source, trans):
    """Fix source words ending with '-' when translation has the full word."""
    # Find tokens like 'knock-' in source (word followed by hyphen and space/end)
    truncated = re.findall(r'\b(\w+)-(?=\s|$)', source)
    if not truncated:
        return source

    trans_lower = trans.lower()
    for word in truncated:
        # Look for the prefix followed by optional hyphen and more chars in translation
        candidates = re.findall(
            r'\b' + re.escape(word) + r'(-?)([\w]+)\b',
            trans_lower,
            flags=re.IGNORECASE,
        )
        if candidates:
            hyphen, rest = candidates[0]
            full = word + hyphen + rest
            source = re.sub(r'\b' + re.escape(word) + r'-(?=\s|$)', full, source)
    return source


def fix_partial_repeats(text):
    """Collapse partial repeats like 'coatings, coating' -> 'coatings'."""
    tokens = re.split(r'(\s+)', text)
    result = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # Check if next non-space token is a repeat/partial of this one
        if i + 2 < len(tokens) and tokens[i + 1].strip() == '' and tokens[i + 2].strip(',').strip():
            next_token = tokens[i + 2].strip(',').strip()
            curr = token.strip(',').strip()
            is_prefix_overlap = (curr.lower().startswith(next_token.lower()) or
                                 next_token.lower().startswith(curr.lower()))
            is_suffix_overlap = (curr.lower().endswith(next_token.lower()) or
                                 next_token.lower().endswith(curr.lower()))
            similar = _similarity(curr, next_token) > 0.7
            if (curr and next_token and similar and
                len(curr) > 1 and len(next_token) > 1 and
                (is_prefix_overlap or is_suffix_overlap)):
                # Keep current token (the longer/cleaner form), skip next token and its whitespace
                result.append(token)
                i += 3
                continue
        result.append(token)
        i += 1

    text = ''.join(result)
    # Clean up double commas/spaces left behind
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def split_merged_sentences(source, trans):
    """Insert a period when source merged two sentences but translation has two."""
    src_sents = count_sentences(source)
    trans_sents = count_sentences(trans)

    if trans_sents <= src_sents:
        return source

    # e.g. "knock- The second" -> "knock-. The second"
    pattern = re.compile(r'(\w[-,])\s+([A-Z][a-z]+)')
    if pattern.search(source):
        source = pattern.sub(r'\1. \2', source, count=1)

    # "word, But/And/So/Now/Then"
    pattern2 = re.compile(r'(\w),\s+(But|And|So|Now|Then)\b')
    if pattern2.search(source):
        source = pattern2.sub(r'\1. \2', source, count=1)

    # If the above did not create enough sentences, try splitting before
    # common sentence-starting words when the translation clearly has more
    # sentences. This handles cases like "knock-in The second is...".
    if count_sentences(source) < trans_sents:
        sentence_starters = r'(The|But|And|So|Then|Now|This|That|These|Those|We|They|He|She|It|You|I)'
        pattern3 = re.compile(r'(\w)\s+(' + sentence_starters + r')\b')
        match = pattern3.search(source)
        if match:
            # Avoid splitting on names/titles: only split if the preceding
            # word is lowercase and the starter is a common subject word.
            before = match.group(1)
            starter = match.group(2)
            if before.islower() and starter[0].isupper():
                source = pattern3.sub(r'\1. \2', source, count=1)

    return source


def fix_comma_sentence_starters(source):
    """Split common sentence starters preceded by a comma into a new sentence."""
    # Handles cases like "...coatings, But now..." -> "...coatings. But now..."
    pattern = re.compile(r',\s+(But|And|So|Then|Now|There)\b')
    if pattern.search(source):
        source = pattern.sub(r'. \1', source, count=1)
    return source


def fix_source_text(source, trans):
    source = fix_truncated_word(source, trans)
    source = fix_partial_repeats(source)
    source = split_merged_sentences(source, trans)
    source = fix_comma_sentence_starters(source)
    return source


def fix_srt_pair(src_path, trans_path, out_path, source_first=True):
    """Fix bilingual SRT where each entry has source on line 1 and translation on line 2."""
    src_entries = parse_srt(src_path)
    trans_entries = parse_srt(trans_path)
    if len(src_entries) != len(trans_entries):
        print("WARNING: Entry count mismatch: {} vs {}".format(len(src_entries), len(trans_entries)))
        return

    fixed = []
    for (idx, times, src_text), (_, _, trans_text) in zip(src_entries, trans_entries):
        new_src = fix_source_text(src_text, trans_text)
        if source_first:
            fixed.append((idx, times, "{}\n{}".format(new_src, trans_text)))
        else:
            fixed.append((idx, times, "{}\n{}".format(trans_text, new_src)))

    fixed = [(str(i), e[1], e[2]) for i, e in enumerate(fixed, 1)]
    write_srt(out_path, fixed)
    print("Fixed bilingual SRT: {}".format(out_path))


def fix_all_srts():
    src_entries = parse_srt(SRC_SRT)
    trans_entries = parse_srt(TRANS_SRT)
    if len(src_entries) != len(trans_entries):
        print("WARNING: src.srt and trans.srt have different entry counts, skipping artifact fix.")
        return

    fixed_src = []
    for (idx, times, src_text), (_, _, trans_text) in zip(src_entries, trans_entries):
        new_src = fix_source_text(src_text, trans_text)
        fixed_src.append((idx, times, new_src))
    fixed_src = [(str(i), e[1], e[2]) for i, e in enumerate(fixed_src, 1)]
    write_srt(SRC_SRT, fixed_src)
    print("Fixed {}".format(SRC_SRT))

    fix_srt_pair(SRC_SRT, TRANS_SRT, SRC_TRANS_SRT, source_first=True)
    fix_srt_pair(SRC_SRT, TRANS_SRT, TRANS_SRC_SRT, source_first=False)


if __name__ == "__main__":
    fix_all_srts()
