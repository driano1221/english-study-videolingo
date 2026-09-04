import json

from core.utils import ask_gpt, check_cancel, load_key


def valid_translate_result(result: dict, expected_count: int):
    translations = result.get("translations") if isinstance(result, dict) else None
    if not isinstance(translations, list) or len(translations) != expected_count:
        return {
            "status": "error",
            "message": f"Expected {expected_count} translations in an ordered list",
        }
    expected_ids = list(range(1, expected_count + 1))
    ids = [item.get("id") for item in translations if isinstance(item, dict)]
    if ids != expected_ids:
        return {"status": "error", "message": "Translation IDs are missing or out of order"}
    if any(not str(item.get("text", "")).strip() for item in translations):
        return {"status": "error", "message": "A translated subtitle is empty"}
    return {"status": "success", "message": "Translation completed"}


def build_translation_prompt(
    lines,
    previous_content=None,
    after_content=None,
    terminology=None,
    theme=None,
):
    """Build a compact one-pass prompt without discarded analysis fields."""
    source_language = load_key("whisper.detected_language")
    target_language = load_key("target_language")
    numbered = [
        {"id": index, "text": line}
        for index, line in enumerate(lines.splitlines(), start=1)
        if line.strip()
    ]
    context = {
        "previous": previous_content or [],
        "next": after_content or [],
        "theme": theme or "",
        "terminology": terminology or "",
    }
    output_example = {
        "translations": [
            {"id": 1, "text": "translation for subtitle 1"},
            {"id": 2, "text": "translation for subtitle 2"},
        ]
    }
    return f"""Translate subtitles from {source_language} to {target_language}.
Return only one JSON object with exactly {len(numbered)} translations. Preserve
every ID from 1 through {len(numbered)} in order. Never join, split, omit or
reorder entries. Translate each subtitle independently but use the context for
consistency. Keep the meaning, technical terms and tone; be natural and concise.
Do not add explanations, analysis, alternatives, markdown or line breaks inside
a translation. Every translated text must be non-empty.

JSON SHAPE EXAMPLE FOR TWO ITEMS:
{json.dumps(output_example, ensure_ascii=False, separators=(',', ':'))}

SUBTITLES:
{json.dumps(numbered, ensure_ascii=False, separators=(',', ':'))}

CONTEXT:
{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}
""".strip()


def translate_lines(
    lines,
    previous_content_prompt,
    after_cotent_prompt,
    things_to_note_prompt,
    summary_prompt,
    index=0,
    validation_retries_override=None,
    temperature_override=None,
):
    del index
    check_cancel()
    source_lines = [line for line in lines.splitlines() if line.strip()]
    prompt = build_translation_prompt(
        "\n".join(source_lines),
        previous_content_prompt,
        after_cotent_prompt,
        things_to_note_prompt,
        summary_prompt,
    )

    result = ask_gpt(
        prompt,
        resp_type="json",
        valid_def=lambda response: valid_translate_result(response, len(source_lines)),
        log_title="translate_batch",
        validation_retries_override=validation_retries_override,
        temperature_override=temperature_override,
    )
    ordered = sorted(result["translations"], key=lambda item: item["id"])
    translations = "\n".join(str(item["text"]).replace("\n", " ").strip() for item in ordered)
    return translations, "\n".join(source_lines)


if __name__ == "__main__":
    print(build_translation_prompt("Hello world.\nThis is a test."))
