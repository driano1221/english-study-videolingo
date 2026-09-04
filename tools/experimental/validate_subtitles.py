"""Extract frames from the final bilingual video to validate subtitle quality."""
import os
import re
import subprocess
import glob
from pathlib import Path

from _bootstrap import REPO_ROOT, WORKSPACE_ROOT, configure_runtime

configure_runtime()

PROJECT_ROOT = WORKSPACE_ROOT
FFMPEG_BIN = WORKSPACE_ROOT / "tools" / "ffmpeg" / "bin"
OUTPUT_DIR = REPO_ROOT / "output"
FRAMES_DIR = OUTPUT_DIR / "validation_frames"


def find_final_video():
    """Find the most recent final bilingual video."""
    candidates = sorted(
        glob.glob(str(PROJECT_ROOT / "*_bilingual_*.mp4")),
        key=os.path.getmtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    fallback = OUTPUT_DIR / "output_sub.mp4"
    if fallback.exists():
        return str(fallback)
    return None


def get_video_duration(video_path: str) -> float:
    env = os.environ.copy()
    env["PATH"] = str(FFMPEG_BIN) + os.pathsep + env.get("PATH", "")
    ffmpeg_exe = str(FFMPEG_BIN / "ffmpeg.exe")
    cmd = [ffmpeg_exe, "-i", video_path]
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", proc.stdout)
    if match:
        h, m, s = map(float, match.groups())
        return h * 3600 + m * 60 + s
    return 0.0


def extract_frames(video_path: str, num_frames: int = 6):
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    duration = get_video_duration(video_path)
    if duration <= 0:
        print("Could not determine video duration.")
        return []

    timestamps = [round(duration * i / (num_frames + 1)) for i in range(1, num_frames + 1)]
    env = os.environ.copy()
    env["PATH"] = str(FFMPEG_BIN) + os.pathsep + env.get("PATH", "")
    ffmpeg_exe = str(FFMPEG_BIN / "ffmpeg.exe")

    extracted = []
    for i, ts in enumerate(timestamps, 1):
        out_path = FRAMES_DIR / f"frame_{i:02d}_{ts:04d}s.jpg"
        cmd = [
            ffmpeg_exe, "-y", "-ss", str(ts), "-i", video_path,
            "-vframes", "1", "-q:v", "2", str(out_path),
        ]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
        )
        if result.returncode == 0:
            extracted.append(str(out_path))
            print(f"Extracted frame at {ts}s -> {out_path}")
        else:
            print(f"Failed to extract frame at {ts}s: {result.stderr[:200]}")
    return extracted


if __name__ == "__main__":
    video = find_final_video()
    if not video:
        print("No final video found.")
        exit(1)
    print(f"Validating: {video}")
    frames = extract_frames(video)
    print(f"\nExtracted {len(frames)} validation frames to: {FRAMES_DIR}")
