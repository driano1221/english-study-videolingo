"""Public core API with lazy pipeline imports.

Importing a single VideoLingo stage used to initialize every ASR, dubbing and
video module.  Besides slowing down startup, that made lightweight utilities
needlessly load large ML dependencies.  Pipeline modules now load only when
they are first requested, while preserving ``from core import _2_asr`` and
``from core import *`` compatibility.
"""

from importlib import import_module

from .utils import *
from .utils.delete_retry_dubbing import delete_dubbing_files
from .utils.onekeycleanup import cleanup


_PIPELINE_MODULES = {
    "_1_ytdlp",
    "_2_asr",
    "_3_1_split_nlp",
    "_3_2_split_meaning",
    "_4_1_summarize",
    "_4_2_translate",
    "_5_split_sub",
    "_6_gen_sub",
    "_7_sub_into_vid",
    "_8_1_audio_task",
    "_8_2_dub_chunks",
    "_9_refer_audio",
    "_10_gen_audio",
    "_11_merge_audio",
    "_12_dub_to_vid",
}


def __getattr__(name):
    if name in _PIPELINE_MODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ask_gpt",
    "load_key",
    "update_key",
    "cleanup",
    "delete_dubbing_files",
    *_PIPELINE_MODULES,
]
