"""Shared path setup for manually executed maintenance scripts."""

from pathlib import Path
import os
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_WORKSPACE = REPO_ROOT.parent
WORKSPACE_ROOT = (
    LEGACY_WORKSPACE
    if (LEGACY_WORKSPACE / "tools" / "ffmpeg" / "bin").is_dir()
    else REPO_ROOT
)


def configure_runtime() -> None:
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    ffmpeg_bin = WORKSPACE_ROOT / "tools" / "ffmpeg" / "bin"
    if ffmpeg_bin.is_dir():
        os.environ["PATH"] = str(ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
