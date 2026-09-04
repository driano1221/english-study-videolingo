import math
from difflib import SequenceMatcher

from rich.console import Console

from core.clean_subtitles import clean_text_lines
from core.local_text import normalized_content, split_balanced, weighted_length
from core.prompts import get_split_prompt
from core.spacy_utils.load_nlp_model import init_nlp
from core.utils import ask_gpt, check_file_exists, get_joiner, load_key
from core.utils.models import _3_1_SPLIT_BY_NLP, _3_2_SPLIT_BY_MEANING


console = Console()


def tokenize_sentence(sentence, nlp):
    return [token.text for token in nlp(sentence) if not token.is_space]


def find_split_positions(original, modified):
    """Map an optional LLM fallback split back to the exact original string."""
    split_positions = []
    parts = modified.split("[br]")
    start = 0
    whisper_language = load_key("whisper.language")
    language = (
        load_key("whisper.detected_language") if whisper_language == "auto" else whisper_language
    )
    joiner = get_joiner(language)

    for part in parts[:-1]:
        modified_left = joiner.join(part.split())
        candidates = range(start + 1, len(original))
        best_split = max(
            candidates,
            key=lambda index: SequenceMatcher(
                None, original[start:index], modified_left
            ).ratio(),
            default=None,
        )
        if best_split is not None:
            split_positions.append(best_split)
            start = best_split
    return split_positions


def split_sentence(sentence, num_parts, word_limit=20, index=-1, retry_attempt=0):
    """LLM fallback retained only for exceptional local-splitting failures."""
    split_prompt = get_split_prompt(sentence, num_parts, word_limit)

    def valid_split(response_data):
        choice = response_data.get("choice")
        selected = response_data.get(f"split{choice}")
        if not selected or "[br]" not in selected:
            return {"status": "error", "message": "Split response has no [br] boundary"}
        return {"status": "success", "message": "Split completed"}

    response_data = ask_gpt(
        split_prompt + " " * retry_attempt,
        resp_type="json",
        valid_def=valid_split,
        log_title="split_by_meaning_fallback",
    )
    selected = response_data[f"split{response_data['choice']}"]
    points = find_split_positions(sentence, selected)
    if len(points) != num_parts - 1:
        raise ValueError("Unable to map LLM split back to the original sentence")
    result = []
    start = 0
    for point in points + [len(sentence)]:
        result.append(sentence[start:point].strip())
        start = point
    return "\n".join(result)


def split_sentence_local(sentence, max_length, nlp, initial_doc=None, max_chars=None):
    """Split a sentence locally while proving that no content was lost."""
    pending = [(" ".join(str(sentence).split()), initial_doc)]
    completed = []
    while pending:
        current, prepared_doc = pending.pop(0)
        doc = prepared_doc if prepared_doc is not None else nlp(current)
        token_count = len([token for token in doc if not token.is_space])
        within_chars = max_chars is None or weighted_length(current) <= max_chars
        if token_count <= max_length and within_chars:
            completed.append(current)
            continue
        parts = max(
            2,
            math.ceil(token_count / max_length),
            math.ceil(weighted_length(current) / max_chars) if max_chars else 1,
        )
        split = split_balanced(current, parts)
        if len(split) <= 1 or normalized_content("".join(split)) != normalized_content(current):
            raise ValueError("Local semantic split did not preserve source content")
        pending = [(part, None) for part in split] + pending
    return completed


def _llm_fallback_enabled():
    try:
        return bool(load_key("local_processing.llm_split_fallback"))
    except (KeyError, TypeError):
        return True


def parallel_split_sentences(
    sentences, max_length, max_workers, nlp, retry_attempt=0, max_chars=None
):
    """Compatibility wrapper; spaCy batching replaces LLM thread fan-out."""
    del max_workers, retry_attempt
    result = []
    for sentence, doc in zip(sentences, nlp.pipe(sentences, batch_size=64)):
        try:
            result.extend(
                split_sentence_local(
                    sentence,
                    max_length,
                    nlp,
                    initial_doc=doc,
                    max_chars=max_chars,
                )
            )
        except Exception:
            if not _llm_fallback_enabled():
                raise
            num_parts = max(2, math.ceil(len(tokenize_sentence(sentence, nlp)) / max_length))
            result.extend(split_sentence(sentence, num_parts, max_length).splitlines())
    return result


@check_file_exists(_3_2_SPLIT_BY_MEANING)
def split_sentences_by_meaning():
    with open(_3_1_SPLIT_BY_NLP, "r", encoding="utf-8") as handle:
        sentences = [line.strip() for line in handle if line.strip()]

    nlp = init_nlp()
    subtitle = load_key("subtitle")
    source_char_limit = float(subtitle["max_length"]) / float(
        subtitle["target_multiplier"]
    )
    sentences = parallel_split_sentences(
        sentences,
        max_length=int(load_key("max_split_length")),
        max_workers=1,
        nlp=nlp,
        max_chars=source_char_limit,
    )
    sentences = clean_text_lines(sentences)

    with open(_3_2_SPLIT_BY_MEANING, "w", encoding="utf-8") as handle:
        handle.write("\n".join(sentences))
    console.print(
        f"[green]Local sentence segmentation complete: {len(sentences)} lines, no LLM calls.[/green]"
    )


if __name__ == "__main__":
    split_sentences_by_meaning()
