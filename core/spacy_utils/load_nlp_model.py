from functools import lru_cache

import spacy
from spacy.cli import download

from core.utils import load_key, rprint


SPACY_MODEL_MAP = load_key("spacy_model_map")


def get_spacy_model(language: str):
    normalized = language.lower()
    model = SPACY_MODEL_MAP.get(normalized, "en_core_web_md")
    if normalized not in SPACY_MODEL_MAP:
        rprint(
            f"[yellow]spaCy does not support '{language}' in config; "
            "using en_core_web_md.[/yellow]"
        )
    return model


@lru_cache(maxsize=4)
def _load_model_cached(model: str):
    rprint(f"[blue]Loading spaCy model once: <{model}>...[/blue]")
    try:
        nlp = spacy.load(model)
    except OSError:
        rprint(f"[yellow]spaCy model {model} is missing; downloading it once.[/yellow]")
        download(model)
        nlp = spacy.load(model)
    rprint(f"[green]spaCy model ready and cached: <{model}>.[/green]")
    return nlp


def init_nlp():
    configured = load_key("whisper.language")
    language = load_key("whisper.detected_language") if configured == "auto" else configured
    return _load_model_cached(get_spacy_model(language))


def spacy_cache_info():
    """Expose cache statistics for diagnostics and tests."""
    return _load_model_cached.cache_info()._asdict()


SPLIT_BY_COMMA_FILE = "output/log/split_by_comma.txt"
SPLIT_BY_CONNECTOR_FILE = "output/log/split_by_connector.txt"
SPLIT_BY_MARK_FILE = "output/log/split_by_mark.txt"
