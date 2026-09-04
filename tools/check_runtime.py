"""Read-only compatibility audit for the current VideoLingo environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path


RECOMMENDED = (3, 11)
PACKAGES = ("openai", "spacy", "torch", "whisperx", "yt-dlp", "pandas")


def audit() -> dict:
    root = Path(__file__).resolve().parents[1]
    bundled_ffmpeg = root.parent / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    ffmpeg = str(bundled_ffmpeg) if bundled_ffmpeg.is_file() else shutil.which("ffmpeg")
    versions = {}
    for package in PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None

    ffmpeg_version = None
    if ffmpeg:
        result = subprocess.run(
            [ffmpeg, "-version"], capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout:
            ffmpeg_version = result.stdout.splitlines()[0]

    current = sys.version_info[:2]
    return {
        "python": ".".join(map(str, sys.version_info[:3])),
        "executable": sys.executable,
        "recommended_python": ".".join(map(str, RECOMMENDED)),
        "migration_required": current < RECOMMENDED,
        "packages": versions,
        "ffmpeg": ffmpeg_version,
        "ready": ffmpeg_version is not None and all(versions.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = audit()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Python: {result['python']} ({result['executable']})")
        print(f"Recommended for the next environment: {result['recommended_python']}")
        print(f"Migration required: {result['migration_required']}")
        print(f"FFmpeg: {result['ffmpeg'] or 'missing'}")
        for package, version in result["packages"].items():
            print(f"{package}: {version or 'missing'}")
    return 1 if args.strict and (result["migration_required"] or not result["ready"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
