import json
import os
import platform
import subprocess
import time

import cv2
import numpy as np

from core._1_ytdlp import find_video_files
from core.utils import *


SRC_FONT_SIZE = 15
TRANS_FONT_SIZE = 17
FONT_NAME = "Arial"
TRANS_FONT_NAME = "Arial"

if platform.system() == "Linux":
    FONT_NAME = "NotoSansCJK-Regular"
    TRANS_FONT_NAME = "NotoSansCJK-Regular"
elif platform.system() == "Darwin":
    FONT_NAME = "Arial Unicode MS"
    TRANS_FONT_NAME = "Arial Unicode MS"

SRC_FONT_COLOR = "&HFFFFFF"
SRC_OUTLINE_COLOR = "&H000000"
SRC_OUTLINE_WIDTH = 1
SRC_SHADOW_COLOR = "&H80000000"
TRANS_FONT_COLOR = "&H00FFFF"
TRANS_OUTLINE_COLOR = "&H000000"
TRANS_OUTLINE_WIDTH = 1
TRANS_BACK_COLOR = "&H33000000"

OUTPUT_DIR = "output"
OUTPUT_VIDEO = f"{OUTPUT_DIR}/output_sub.mp4"
OUTPUT_FAST_VIDEO = f"{OUTPUT_DIR}/output_sub.mkv"
SRC_SRT = f"{OUTPUT_DIR}/src.srt"
TRANS_SRT = f"{OUTPUT_DIR}/trans.srt"
SRC_TRANS_SRT = f"{OUTPUT_DIR}/src_trans.srt"
BILINGUAL_ASS = f"{OUTPUT_DIR}/bilingual.ass"
MIN_VALID_VIDEO_BYTES = 1024
VALID_SUBTITLE_MODES = {"bilingual", "portuguese", "english"}
VALID_OUTPUT_FORMATS = {"burned", "fast"}


def _run(command, *, capture_output=False, timeout=None):
    return subprocess.run(
        command,
        capture_output=capture_output,
        text=capture_output,
        timeout=timeout,
        check=False,
    )


def check_encoder_available(encoder="h264_nvenc"):
    """Return True only when a hardware encoder can encode a real frame.

    Listing ``h264_nvenc`` in ``ffmpeg -encoders`` is insufficient: the bundled
    FFmpeg may target a newer NVENC API than the installed NVIDIA driver.
    """
    probe = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=size=64x64:rate=1:duration=0.1",
        "-frames:v",
        "1",
        "-c:v",
        encoder,
        "-f",
        "null",
        "-",
    ]
    try:
        return _run(probe, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check_gpu_available():
    """Backward-compatible NVENC probe."""
    return check_encoder_available("h264_nvenc")


def probe_video(path):
    """Return ffprobe metadata for a valid video, otherwise raise RuntimeError."""
    if not os.path.isfile(path):
        raise RuntimeError(f"Final video was not created: {path}")
    size = os.path.getsize(path)
    if size < MIN_VALID_VIDEO_BYTES:
        raise RuntimeError(f"Final video is invalid ({size} bytes): {path}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height",
        "-of",
        "json",
        path,
    ]
    try:
        result = _run(command, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Unable to validate final video: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "ffprobe failed").strip()
        raise RuntimeError(f"Final video validation failed: {detail}")

    try:
        metadata = json.loads(result.stdout)
        duration = float(metadata.get("format", {}).get("duration", 0))
        streams = metadata.get("streams", [])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("ffprobe returned invalid metadata") from exc
    stream_types = {stream.get("codec_type") for stream in streams}
    if duration <= 0 or "video" not in stream_types:
        raise RuntimeError("Final video has no playable video stream or duration")
    if "audio" not in stream_types:
        raise RuntimeError("Final video has no playable audio stream")
    metadata["validated_size"] = size
    return metadata


def _video_dimensions(video_file):
    video = cv2.VideoCapture(video_file)
    try:
        width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        video.release()
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Unable to read input video dimensions: {video_file}")
    return width, height


def normalize_subtitle_mode(subtitle_mode):
    mode = str(subtitle_mode or "bilingual").strip().lower()
    if mode not in VALID_SUBTITLE_MODES:
        raise ValueError(f"Unsupported subtitle mode: {subtitle_mode}")
    return mode


def normalize_output_format(output_format):
    value = str(output_format or "burned").strip().lower()
    if value not in VALID_OUTPUT_FORMATS:
        raise ValueError(f"Unsupported output format: {output_format}")
    return value


def _ass_time(seconds):
    centiseconds = max(0, round(float(seconds) * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _ass_text(value):
    return str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _write_bilingual_ass(
    width,
    height,
    subtitle_scale=1.0,
    output_path=BILINGUAL_ASS,
    source_path=SRC_SRT,
    translation_path=TRANS_SRT,
):
    """Create one styled event per pair so libass stacks wrapped lines safely."""
    from pathlib import Path
    from core.youtube_subtitles import parse_srt

    source = parse_srt(Path(source_path))
    translation = parse_srt(Path(translation_path))
    if not source or len(source) != len(translation):
        raise RuntimeError("Source and translation subtitles are not paired")
    # ASS uses the explicit video canvas, while libass scales SRT's implicit
    # canvas. Doubling preserves the visual size users already selected.
    font_size = max(18, round(SRC_FONT_SIZE * float(subtitle_scale) * 2))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bilingual,{FONT_NAME},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,18,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for english, portuguese in zip(source, translation):
        text = (
            r"{\c&H00B8F4FF&}" + _ass_text(portuguese["text"])
            + r"\N{\c&H00FFFFFF&}" + _ass_text(english["text"])
        )
        events.append(
            f"Dialogue: 0,{_ass_time(english['start'])},{_ass_time(english['end'])},"
            f"Bilingual,,0,0,0,,{text}"
        )
    Path(output_path).write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return output_path


def _subtitle_filter(width, height, subtitle_mode, subtitle_scale=1.0):
    mode = normalize_subtitle_mode(subtitle_mode)
    subtitle_scale = float(subtitle_scale)
    if not 0.6 <= subtitle_scale <= 1.5:
        raise ValueError(f"Unsupported subtitle scale: {subtitle_scale}")
    source_size = max(9, round(SRC_FONT_SIZE * subtitle_scale))
    translation_size = max(9, round(TRANS_FONT_SIZE * subtitle_scale))
    base = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )
    source = (
        f"subtitles={SRC_SRT}:force_style='FontSize={translation_size},FontName={FONT_NAME},"
        f"PrimaryColour={SRC_FONT_COLOR},OutlineColour={SRC_OUTLINE_COLOR},OutlineWidth={SRC_OUTLINE_WIDTH},"
        f"ShadowColour={SRC_SHADOW_COLOR},Alignment=2,MarginV=18,BorderStyle=1'"
    )
    translation = (
        f"subtitles={TRANS_SRT}:force_style='FontSize={translation_size},FontName={TRANS_FONT_NAME},"
        f"PrimaryColour={TRANS_FONT_COLOR},OutlineColour={TRANS_OUTLINE_COLOR},OutlineWidth={TRANS_OUTLINE_WIDTH},"
        f"BackColour={TRANS_BACK_COLOR},Alignment=2,MarginV=18,BorderStyle=4'"
    )
    if mode == "english":
        return f"{base},{source}"
    if mode == "portuguese":
        return f"{base},{translation}"
    return f"{base},subtitles={BILINGUAL_ASS}"


def _ffmpeg_command(
    video_file, width, height, encoder, subtitle_mode="bilingual", subtitle_scale=1.0
):
    subtitle_filter = _subtitle_filter(width, height, subtitle_mode, subtitle_scale)
    command = ["ffmpeg", "-hide_banner", "-y", "-i", video_file, "-vf", subtitle_filter]
    if encoder == "h264_nvenc":
        command.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"])
    elif encoder == "h264_qsv":
        command.extend(["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23"])
    else:
        command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])
    command.extend(["-c:a", "aac", "-movflags", "+faststart", OUTPUT_VIDEO])
    return command


def _fast_ffmpeg_command(video_file, subtitle_mode="bilingual"):
    mode = normalize_subtitle_mode(subtitle_mode)
    subtitle = {
        "english": SRC_SRT,
        "portuguese": TRANS_SRT,
        "bilingual": SRC_TRANS_SRT,
    }[mode]
    language = "eng" if mode == "english" else "por"
    return [
        "ffmpeg", "-hide_banner", "-y", "-i", video_file, "-i", subtitle,
        "-map", "0:v:0", "-map", "0:a:0?", "-map", "1:0",
        "-c:v", "copy", "-c:a", "copy", "-c:s", "srt",
        "-metadata:s:s:0", f"language={language}", "-disposition:s:0", "default",
        OUTPUT_FAST_VIDEO,
    ]


def _encode_video(command, encoder, output_path=OUTPUT_VIDEO):
    if os.path.exists(output_path):
        os.remove(output_path)
    rprint(f"[cyan]Encoding final video with {encoder}...[/cyan]")
    result = _run(command)
    if result.returncode != 0:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise RuntimeError(f"FFmpeg failed with encoder {encoder} (exit code {result.returncode})")
    metadata = probe_video(output_path)
    metadata["encoder_used"] = encoder
    return metadata


def merge_subtitles_to_video(
    subtitle_mode="bilingual", output_format="burned", subtitle_scale=1.0
):
    from core._1_ytdlp import is_audio_only_input

    subtitle_mode = normalize_subtitle_mode(subtitle_mode)
    output_format = normalize_output_format(output_format)

    if is_audio_only_input():
        rprint("[bold green]Audio-only input: skipping video merge. Subtitle files are ready in the output directory.[/bold green]")
        return None

    video_file = find_video_files()
    os.makedirs(os.path.dirname(OUTPUT_VIDEO), exist_ok=True)

    if output_format == "burned" and not load_key("burn_subtitles"):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, 1, (1920, 1080))
        out.write(frame)
        out.release()
        return probe_video(OUTPUT_VIDEO)

    required_subtitles = {
        "english": (SRC_SRT,),
        "portuguese": (TRANS_SRT,),
        "bilingual": (SRC_SRT, TRANS_SRT) if output_format == "burned" else (SRC_TRANS_SRT,),
    }[subtitle_mode]
    missing = [path for path in required_subtitles if not os.path.isfile(path)]
    if missing:
        raise FileNotFoundError(f"Subtitle files not found: {', '.join(missing)}")

    start_time = time.time()
    if output_format == "fast":
        metadata = _encode_video(
            _fast_ffmpeg_command(video_file, subtitle_mode),
            "stream_copy",
            OUTPUT_FAST_VIDEO,
        )
        rprint(
            f"[bold green]Fast video validated: {float(metadata['format']['duration']):.2f}s, "
            f"{metadata['validated_size'] / (1024 * 1024):.2f} MiB. "
            f"Time taken: {time.time() - start_time:.2f}s[/bold green]"
        )
        return metadata

    width, height = _video_dimensions(video_file)
    rprint(f"[bold green]Video resolution: {width}x{height}[/bold green]")
    rprint(f"[bold green]Subtitle output mode: {subtitle_mode}[/bold green]")
    if subtitle_mode == "bilingual":
        _write_bilingual_ass(width, height, subtitle_scale)
    requested_gpu = bool(load_key("ffmpeg_gpu"))
    candidates = []
    if requested_gpu:
        candidates.extend(("h264_nvenc", "h264_qsv"))
    candidates.append("libx264")

    metadata = None
    for encoder in candidates:
        if encoder != "libx264" and not check_encoder_available(encoder):
            rprint(f"[bold yellow]{encoder} indisponível ou incompatível; tentando o próximo encoder.[/bold yellow]")
            continue
        try:
            metadata = _encode_video(
                _ffmpeg_command(
                    video_file, width, height, encoder, subtitle_mode, subtitle_scale
                ),
                encoder,
            )
            break
        except RuntimeError as exc:
            rprint(f"[bold yellow]{exc}. Tentando o próximo encoder.[/bold yellow]")
    if metadata is None:
        raise RuntimeError("Nenhum encoder conseguiu gerar o vídeo final")

    duration = float(metadata["format"]["duration"])
    size_mb = metadata["validated_size"] / (1024 * 1024)
    rprint(
        f"[bold green]Final video validated: {duration:.2f}s, {size_mb:.2f} MiB. "
        f"Time taken: {time.time() - start_time:.2f}s[/bold green]"
    )
    return metadata


if __name__ == "__main__":
    merge_subtitles_to_video()
