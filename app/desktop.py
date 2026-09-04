import os
import sys
import json
import subprocess
import threading
import shutil
import re
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path

from app.pipeline_cache import JobCache, build_job_id

# --- Project paths ---
def _is_workspace(path: Path) -> bool:
    """Return whether *path* contains either a standalone or legacy install."""
    return (path / "config.yaml").is_file() or (
        path / "VideoLingo" / "config.yaml"
    ).is_file()


def _find_project_dir() -> Path:
    """Locate runtime data without tying the source tree to one Windows path."""
    if getattr(sys, 'frozen', False):
        home = Path.home()
        candidates = [
            Path(sys.executable).resolve().parent,
            Path(sys.executable).resolve().parent.parent,
            home / "english-study-videolingo",
            home / "Desktop" / "english-study-videolingo",
            home / "OneDrive" / "english-study-videolingo",
            home / "OneDrive" / "Desktop" / "english-study-videolingo",
        ]
        for candidate in candidates:
            if _is_workspace(candidate):
                return candidate
        return home / "english-study-videolingo"

    repo_dir = Path(__file__).resolve().parents[1]
    legacy_workspace = repo_dir.parent
    if (
        repo_dir.name.casefold() == "videolingo"
        and (legacy_workspace / "cache").is_dir()
        and (legacy_workspace / "videos").is_dir()
    ):
        return legacy_workspace
    return repo_dir


PROJECT_DIR = _find_project_dir()
VIDEO_LINGO_DIR = (
    PROJECT_DIR if (PROJECT_DIR / "config.yaml").is_file()
    else PROJECT_DIR / "VideoLingo"
)
OUTPUT_DIR = VIDEO_LINGO_DIR / "output"
CONFIG_FILE = VIDEO_LINGO_DIR / "config.yaml"
FFMPEG_BIN = PROJECT_DIR / "tools" / "ffmpeg" / "bin"
VENV_PYTHON_310 = VIDEO_LINGO_DIR / ".venv" / "Scripts" / "python.exe"
VENV_PYTHON_312 = VIDEO_LINGO_DIR / ".venv312" / "Scripts" / "python.exe"
VENV_PYTHON = (
    VENV_PYTHON_312
    if os.environ.get("VIDEOLINGO_PYTHON", "").strip() == "3.12" and VENV_PYTHON_312.is_file()
    else VENV_PYTHON_310
)
DESKTOP_DIR = Path.home() / "Desktop"
CACHE_ROOT = PROJECT_DIR / "cache"
FINAL_OUTPUT_DIR = PROJECT_DIR / "videos" / "finalizados"

# --- Language options for VideoLingo target_language ---
LANGUAGES = {
    "Português brasileiro": "pt",
    "Español": "es",
    "Français": "fr",
    "Deutsch": "de",
    "Italiano": "it",
    "Русский": "ru",
    "中文（简体）": "zh",
    "日本語": "ja",
}

RESOLUTIONS = ["360", "480", "720", "1080", "best"]

OUTPUT_MODES = {
    "Duas legendas": "bilingual",
    "Somente português": "portuguese",
    "Somente inglês": "english",
}

OUTPUT_SUFFIXES = {
    "bilingual": "bilingual",
    "portuguese": "pt-br",
    "english": "english",
}

OUTPUT_FORMATS = {
    "Compatível (MP4, legenda fixa)": "burned",
    "Rápido (MKV, legenda ativável)": "fast",
}

INFERENCE_PROFILES = {
    "Grátis": "free",
    "Equilibrado": "balanced",
    "Máxima robustez": "robust",
}

SUBTITLE_SIZES = {
    "Pequena": 0.75,
    "Média": 1.0,
    "Grande": 1.20,
}


def build_output_filename(title: str, subtitle_mode: str, output_format="burned") -> str:
    try:
        suffix = OUTPUT_SUFFIXES[subtitle_mode]
    except KeyError as exc:
        raise ValueError(f"Modo de legenda inválido: {subtitle_mode}") from exc
    if output_format not in {"burned", "fast"}:
        raise ValueError(f"Formato de saída inválido: {output_format}")
    extension = ".mkv" if output_format == "fast" else ".mp4"
    fast_suffix = "_fast" if output_format == "fast" else ""
    return f"{title}_{suffix}{fast_suffix}{extension}"


def read_api_usage_summary(output_dir: Path = OUTPUT_DIR) -> dict:
    """Read the per-job API totals without failing the completed video flow."""
    defaults = {
        "api_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "estimated_cost_usd": 0.0,
    }
    path = output_dir / "gpt_log" / "usage_summary.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return defaults
        return {
            "api_calls": int(payload.get("api_calls", 0) or 0),
            "prompt_tokens": int(payload.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(payload.get("completion_tokens", 0) or 0),
            "reasoning_tokens": int(payload.get("reasoning_tokens", 0) or 0),
            "estimated_cost_usd": float(payload.get("estimated_cost_usd", 0) or 0),
        }
    except (OSError, TypeError, ValueError):
        return defaults


def format_api_usage(summary: dict) -> str:
    """Return a compact Brazilian-Portuguese API usage summary."""
    calls = int(summary.get("api_calls", 0) or 0)
    tokens = (
        int(summary.get("prompt_tokens", 0) or 0)
        + int(summary.get("completion_tokens", 0) or 0)
    )
    cost = float(summary.get("estimated_cost_usd", 0) or 0)
    cost_text = f"US$ {cost:.8f}".replace(".", ",")
    tokens_text = f"{tokens:,}".replace(",", ".")
    return f"Custo estimado da API: {cost_text}\nChamadas: {calls} | Tokens: {tokens_text}"


def finalize_run_metrics(destination: Path, usage_summary: dict) -> dict:
    """Attach parent-process facts to the metrics emitted by the pipeline."""
    path = OUTPUT_DIR / "log" / "run_metrics.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        payload["api_usage"] = usage_summary
        payload["final_output"] = str(destination)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        return payload
    except (OSError, TypeError, ValueError):
        return {}


def format_run_metrics(metrics: dict) -> str:
    if not metrics:
        return "Métricas detalhadas indisponíveis."
    resources = metrics.get("resources") or {}
    coverage = metrics.get("subtitle_coverage") or {}
    encoder = metrics.get("encoder") or "não informado"
    rtf = metrics.get("asr_rtf")
    rtf_text = "dispensado" if rtf == 0 else (f"{float(rtf):.3f}x" if rtf is not None else "n/d")
    coverage_ratio = coverage.get("timeline_coverage_ratio")
    coverage_text = f"{float(coverage_ratio) * 100:.1f}%" if coverage_ratio is not None else "n/d"
    vram = resources.get("peak_nvidia_vram_mib")
    vram_text = f"{float(vram):.0f} MiB" if vram is not None else "n/d"
    runtime = metrics.get("asr_runtime") or {}
    asr_detail = ""
    if runtime:
        asr_detail = (
            f" | batch {runtime.get('selected_batch', 'n/d')}"
            f" | gaps reparados {runtime.get('gaps_repaired', 0)}"
        )
    return (
        f"Métricas: encoder {encoder} | RTF ASR {rtf_text} | "
        f"cobertura temporal {coverage_text} | pico VRAM NVIDIA {vram_text}{asr_detail}"
    )


def clean_output():
    """Remove previous run artifacts from VideoLingo output folder."""
    if not OUTPUT_DIR.exists():
        return
    for name in ["audio", "gpt_log", "log", "src.srt", "trans.srt",
                 "src_trans.srt", "trans_src.srt", "output_sub.mp4",
                 "input_manifest.json"]:
        path = OUTPUT_DIR / name
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink()
        except Exception:
            pass
    for ext in ("*.mp4", "*.webm", "*.mkv", "*.mov", "*.avi", "*.flv", "*.wmv",
                "*.jpg", "*.jpeg", "*.webp", "*.png"):
        for path in OUTPUT_DIR.glob(ext):
            try:
                path.unlink()
            except Exception:
                pass


def update_config(resolution: str, target_language: str):
    """Update VideoLingo config.yaml with selected resolution and target language."""
    if not CONFIG_FILE.exists():
        return
    text = CONFIG_FILE.read_text(encoding="utf-8")
    text = re.sub(r"^(target_language:\s*').*?(')",
                  rf"\g<1>{target_language}\g<2>", text, flags=re.MULTILINE)
    text = re.sub(r"^(ytb_resolution:\s*').*?(')",
                  rf"\g<1>{resolution}\g<2>", text, flags=re.MULTILINE)
    CONFIG_FILE.write_text(text, encoding="utf-8")


def migrate_legacy_api_key():
    """Move a legacy YAML API key into the Windows user profile."""
    if not VENV_PYTHON.is_file() or not CONFIG_FILE.is_file():
        return False
    result = subprocess.run(
        [
            str(VENV_PYTHON),
            "-c",
            "from core.utils.config_utils import migrate_api_key_from_config; "
            "print(int(migrate_api_key_from_config()))",
        ],
        cwd=str(VIDEO_LINGO_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0 and result.stdout.strip().endswith("1")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.strip('. ')
    return name or "video"


def get_video_metadata(url: str) -> dict:
    """Fetch title and description once for naming and ASR hotwords."""
    env = os.environ.copy()
    env["PATH"] = str(FFMPEG_BIN) + os.pathsep + env.get("PATH", "")
    env["HF_HUB_DISABLE_SYMLINKS"] = "1"
    try:
        result = subprocess.run(
            [
                str(VENV_PYTHON), "-m", "yt_dlp", "--dump-single-json",
                "--skip-download", "--no-warnings", url,
            ],
            cwd=str(VIDEO_LINGO_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            payload = json.loads(result.stdout)
            return {
                "title": sanitize_filename(str(payload.get("title") or "video")),
                "description": str(payload.get("description") or "")[:6000],
            }
    except Exception:
        pass
    return {"title": "video", "description": ""}


def get_video_title(url: str) -> str:
    return get_video_metadata(url)["title"]


def validate_video_file(path: Path) -> dict:
    """Validate that a final file is non-empty, playable, and has a video stream."""
    if not path.is_file() or path.stat().st_size < 1024:
        size = path.stat().st_size if path.exists() else 0
        raise RuntimeError(f"Video final inválido ou vazio ({size} bytes): {path}")
    ffprobe = FFMPEG_BIN / "ffprobe.exe"
    executable = str(ffprobe) if ffprobe.is_file() else "ffprobe"
    result = subprocess.run(
        [
            executable, "-v", "error",
            "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Falha ao validar vídeo final: {result.stderr.strip()}")
    metadata = json.loads(result.stdout)
    duration = float(metadata.get("format", {}).get("duration", 0))
    stream_types = {stream.get("codec_type") for stream in metadata.get("streams", [])}
    if duration <= 0 or "video" not in stream_types:
        raise RuntimeError("Vídeo final sem duração ou faixa de vídeo reproduzível")
    if "audio" not in stream_types:
        raise RuntimeError("Video final sem faixa de audio reproduzivel")
    metadata["validated_size"] = path.stat().st_size
    return metadata


def run_processing(url: str, resolution: str, target_language: str,
                   log_callback, done_callback, error_callback,
                   progress_callback=None, subtitle_mode="bilingual",
                   output_format="burned", inference_profile="balanced",
                   subtitle_scale=1.0):
    """Run VideoLingo pipeline in a subprocess and stream output.

    progress_callback receives (percent: float, status_text: str).
    """
    env = os.environ.copy()
    env["PATH"] = str(FFMPEG_BIN) + os.pathsep + env.get("PATH", "")
    env["HF_HUB_DISABLE_SYMLINKS"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    if subtitle_mode not in OUTPUT_SUFFIXES:
        error_callback(f"Modo de legenda inválido: {subtitle_mode}")
        return
    if output_format not in {"burned", "fast"}:
        error_callback(f"Formato de saída inválido: {output_format}")
        return
    if inference_profile not in set(INFERENCE_PROFILES.values()):
        error_callback(f"Perfil de inferência inválido: {inference_profile}")
        return
    if float(subtitle_scale) not in set(SUBTITLE_SIZES.values()):
        error_callback(f"Tamanho de legenda inválido: {subtitle_scale}")
        return

    update_config(resolution, target_language)
    job_id = build_job_id(
        url, resolution, target_language, CONFIG_FILE,
        inference_profile=inference_profile,
    )
    cache = JobCache(OUTPUT_DIR, CACHE_ROOT)

    script = f'''
import os, sys, shutil, re, json
os.chdir(r"{VIDEO_LINGO_DIR}")
sys.path.insert(0, os.getcwd())
os.environ["PATH"] = r"{FFMPEG_BIN}" + os.pathsep + os.environ.get("PATH", "")
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

from core._1_ytdlp import download_video_ytdlp, _safe_find_video_file
from core.youtube_subtitles import load_prepared_youtube_subtitles, try_prepare_youtube_subtitles
from core.asr_quality import validate_asr_transcription
from core.utils.models import _2_CLEANED_CHUNKS
from core.run_metrics import RunMetrics, subtitle_coverage
from core import _2_asr, _3_1_split_nlp, _3_2_split_meaning
from core import _4_1_summarize, _4_2_translate, _5_split_sub, _6_gen_sub, _7_sub_into_vid

url = {url!r}
resolution = {resolution!r}
output_format = {output_format!r}
with RunMetrics() as metrics:
    metrics.record(
        url=url, resolution=resolution, subtitle_mode={subtitle_mode!r},
        output_format=output_format, inference_profile={inference_profile!r},
        subtitle_scale={float(subtitle_scale)!r},
    )
    print("[1/6] Baixando vídeo do YouTube...")
    with metrics.stage("download"):
        existing_video = _safe_find_video_file("output")
        if existing_video:
            print(f"[CACHE] Reutilizando vídeo: {{existing_video}}")
        else:
            download_video_ytdlp(url, save_path="output", resolution=resolution)
            existing_video = _safe_find_video_file("output")
    media_metadata = _7_sub_into_vid.probe_video(existing_video)
    media_duration = float(media_metadata["format"]["duration"])
    metrics.record(media_duration_seconds=round(media_duration, 3))
    with metrics.stage("subtitle_source"):
        official_subtitles = load_prepared_youtube_subtitles()
        if official_subtitles:
            print(f"[CACHE] Reutilizando {{official_subtitles['entries']}} legendas pareadas; sem rede ou API.")
        else:
            official_subtitles = try_prepare_youtube_subtitles(url, {target_language!r})
    if official_subtitles:
        metrics.record(transcription_source=official_subtitles.get("source", "youtube"), asr_rtf=0.0)
        print("[2/6] Legendas completas encontradas no YouTube.")
        print("[3/6] Transcrição local dispensada.")
        if official_subtitles["source"].endswith("_api_translated"):
            print("[4/6] Faixa inglesa confiável traduzida em lotes.")
        else:
            print("[4/6] Tradução por API dispensada.")
        print("[5/6] Legendas bilíngues sincronizadas.")
    else:
        metrics.record(transcription_source="whisperx")
        print("[2/6] Transcrição com WhisperX...")
        with metrics.stage("asr"):
            _2_asr.transcribe({inference_profile!r})
            validate_asr_transcription(_2_CLEANED_CHUNKS)
        metrics.record(asr_rtf=round(metrics.stage_seconds("asr") / media_duration, 4) if media_duration else None)
        if os.path.isfile("output/log/asr_runtime.json"):
            with open("output/log/asr_runtime.json", encoding="utf-8") as handle:
                metrics.record(asr_runtime=json.load(handle))
        print("[3/6] Segmentação de frases...")
        with metrics.stage("sentence_segmentation"):
            _3_1_split_nlp.split_by_spacy()
            _3_2_split_meaning.split_sentences_by_meaning()
        print("[4/6] Resumo e tradução...")
        with metrics.stage("translation"):
            _4_1_summarize.get_summary()
            _4_2_translate.translate_all()
        print("[5/6] Alinhamento das legendas...")
        with metrics.stage("subtitle_alignment"):
            _5_split_sub.split_for_sub_main()
            _6_gen_sub.align_timestamp_main()
    action = "Anexando legenda ativável" if output_format == "fast" else "Queimando legendas"
    print(f"[6/6] {{action}} no vídeo...")
    with metrics.stage("final_render"):
        final_metadata = _7_sub_into_vid.merge_subtitles_to_video(
            {subtitle_mode!r}, output_format, {float(subtitle_scale)!r}
        )
    coverage_file = {{"english": "output/src.srt", "portuguese": "output/trans.srt", "bilingual": "output/src_trans.srt"}}[{subtitle_mode!r}]
    metrics.record(
        encoder=final_metadata.get("encoder_used") if final_metadata else None,
        subtitle_coverage=subtitle_coverage(coverage_file, media_duration),
    )
print("DONE")
'''

    # Map pipeline stage markers to progress percent
    stage_progress = {
        "[1/6]": (5, "Baixando vídeo..."),
        "[2/6]": (25, "Transcrevendo áudio..."),
        "[3/6]": (35, "Segmentando frases..."),
        "[4/6]": (75, "Traduzindo legendas..."),
        "[5/6]": (88, "Alinhando legendas..."),
        "[6/6]": (95, "Gerando vídeo final..."),
    }

    try:
        compacted = cache.compact_existing_jobs()
        disk = cache.ensure_free_space(resolution)
        if compacted["bytes_removed"]:
            log_callback(
                f"Cache otimizado: {compacted['bytes_removed'] / 1024**3:.2f} GB liberados.\n"
            )
        log_callback(
            f"Espaço livre validado: {disk['free_bytes'] / 1024**3:.1f} GB.\n"
        )
        restored = cache.prepare(
            job_id,
            url=url,
            resolution=resolution,
            target_language=target_language,
        )
        metadata = cache.active_metadata()
        video_context = {}
        if not metadata.get("title") or "description" not in metadata:
            video_context = get_video_metadata(url)
        title = metadata.get("title") or video_context.get("title") or "video"
        description = metadata.get("description", video_context.get("description", ""))
        cache.update_active_metadata(
            title=title,
            description=description,
            status="running",
            subtitle_mode=subtitle_mode,
            output_format=output_format,
            inference_profile=inference_profile,
            subtitle_scale=float(subtitle_scale),
        )
        if restored:
            log_callback(f"Cache restaurado para esta tarefa: {job_id}\n")
        log_callback(f"Título detectado: {title}\n")

        process = subprocess.Popen(
            [str(VENV_PYTHON), "-c", script],
            cwd=str(VIDEO_LINGO_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        current_progress = 0
        for line in process.stdout:
            if line:
                log_callback(line)
                # Update progress based on stage markers
                for marker, (pct, status) in stage_progress.items():
                    if marker in line:
                        if progress_callback and pct > current_progress:
                            current_progress = pct
                            progress_callback(pct, status)
                        break

        process.wait()

        if process.returncode != 0:
            cache.update_active_metadata(status="error", return_code=process.returncode)
            error_callback("O processamento falhou. Verifique o log acima.")
            return

        source_name = "output_sub.mkv" if output_format == "fast" else "output_sub.mp4"
        source = OUTPUT_DIR / source_name
        source_metadata = validate_video_file(source)
        if not source.exists():
            error_callback(f"Vídeo final não encontrado em output/{source_name}")
            return

        final_name = build_output_filename(title, subtitle_mode, output_format)
        FINAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        destination = FINAL_OUTPUT_DIR / final_name
        counter = 1
        while destination.exists():
            stem = Path(final_name).stem
            destination = FINAL_OUTPUT_DIR / f"{stem}_{counter}{Path(final_name).suffix}"
            counter += 1

        shutil.copy2(str(source), str(destination))
        validate_video_file(destination)
        usage_summary = read_api_usage_summary()
        run_metrics = finalize_run_metrics(destination, usage_summary)
        cache.update_active_metadata(
            status="completed",
            error=None,
            final_duration=float(source_metadata["format"]["duration"]),
            final_size=source_metadata["validated_size"],
            api_calls=usage_summary["api_calls"],
            api_tokens=(
                usage_summary["prompt_tokens"]
                + usage_summary["completion_tokens"]
            ),
            estimated_cost_usd=usage_summary["estimated_cost_usd"],
            encoder=run_metrics.get("encoder"),
            asr_rtf=run_metrics.get("asr_rtf"),
            subtitle_coverage=(run_metrics.get("subtitle_coverage") or {}).get(
                "timeline_coverage_ratio"
            ),
        )
        log_callback(f"\n{format_api_usage(usage_summary)}\n")
        log_callback(f"{format_run_metrics(run_metrics)}\n")
        done_callback(str(destination), usage_summary)

    except Exception as e:
        try:
            cache.update_active_metadata(status="error", error=str(e))
        except Exception:
            pass
        error_callback(str(e))
    finally:
        try:
            cache.save_active()
        except Exception as cache_error:
            log_callback(f"Aviso: não foi possível salvar o cache: {cache_error}\n")


class VideoLingoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("VideoLingo // English Lab")
        self.root.geometry("900x820")
        self.root.minsize(800, 700)

        bg = "#080B16"
        panel = "#101728"
        cyan = "#32E6E2"
        magenta = "#FF4FA3"
        text_color = "#E8F7FF"
        muted = "#7E9BB7"
        self.root.configure(bg=bg)
        self.root.option_add("*Font", ("Bahnschrift", 10))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("TLabel", background=bg, foreground=text_color, font=("Bahnschrift", 10))
        style.configure("Muted.TLabel", background=bg, foreground=muted, font=("Bahnschrift", 9))
        style.configure("Panel.TLabel", background=panel, foreground=text_color, font=("Bahnschrift", 10))
        style.configure("PanelMuted.TLabel", background=panel, foreground=muted, font=("Bahnschrift", 8))
        style.configure(
            "TButton", background=cyan, foreground=bg, borderwidth=0,
            font=("Bahnschrift SemiBold", 10), padding=(16, 9),
        )
        style.map("TButton", background=[("active", "#78FFF8"), ("disabled", "#26354A")])
        style.configure("Secondary.TButton", background=panel, foreground=cyan, borderwidth=1)
        style.map("Secondary.TButton", background=[("active", "#17243A")])
        style.configure(
            "TEntry", fieldbackground=panel, foreground=text_color,
            insertcolor=cyan, bordercolor="#27405A", padding=9,
        )
        style.configure(
            "TCombobox", fieldbackground=panel, background=panel,
            foreground=text_color, arrowcolor=cyan, padding=6,
        )
        style.map("TCombobox", fieldbackground=[("readonly", panel)], foreground=[("readonly", text_color)])
        style.configure(
            "TRadiobutton", background=panel, foreground=text_color,
            indicatorcolor="#26354A", font=("Bahnschrift", 9), padding=3,
        )
        style.map(
            "TRadiobutton",
            indicatorcolor=[("selected", magenta), ("active", cyan)],
            background=[("active", panel)],
        )
        style.configure(
            "Horizontal.TProgressbar", thickness=7,
            troughcolor=panel, background=magenta, borderwidth=0,
        )

        # Header
        header = ttk.Label(
            root, text="VIDEOLINGO // 80", font=("Bahnschrift SemiBold", 24), foreground=cyan
        )
        header.pack(pady=(22, 2))
        ttk.Label(
            root, text="ENGLISH STUDY LAB", font=("Consolas", 9), foreground=magenta
        ).pack(pady=(0, 18))

        # URL input
        frame_url = ttk.Frame(root)
        frame_url.pack(fill="x", padx=38, pady=5)
        ttk.Label(frame_url, text="LINK DO YOUTUBE", foreground=muted).pack(anchor="w")
        self.url_entry = ttk.Entry(frame_url, font=("Bahnschrift", 11))
        self.url_entry.pack(fill="x", pady=(5, 0))
        self.url_entry.bind("<Return>", lambda e: self.start_processing())

        # Options
        frame_options = ttk.Frame(root, style="Panel.TFrame", padding=(18, 14))
        frame_options.pack(fill="x", padx=38, pady=14)
        frame_options.columnconfigure(3, weight=1)

        ttk.Label(frame_options, text="IDIOMA", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.lang_var = tk.StringVar(value="Português brasileiro")
        self.lang_combo = ttk.Combobox(frame_options, textvariable=self.lang_var,
                                       values=list(LANGUAGES.keys()), state="readonly", width=22)
        self.lang_combo.grid(row=0, column=1, padx=(10, 20), sticky="w")

        ttk.Label(frame_options, text="RESOLUÇÃO", style="Panel.TLabel").grid(row=0, column=2, sticky="w")
        self.res_var = tk.StringVar(value="1080")
        self.res_combo = ttk.Combobox(frame_options, textvariable=self.res_var,
                                      values=RESOLUTIONS, state="readonly", width=10)
        self.res_combo.grid(row=0, column=3, padx=(10, 0), sticky="w")

        ttk.Label(frame_options, text="LEGENDA", style="Panel.TLabel").grid(row=1, column=0, sticky="nw", pady=(14, 0))
        self.output_mode_label_var = tk.StringVar(value="Duas legendas")
        mode_frame = ttk.Frame(frame_options, style="Panel.TFrame")
        mode_frame.grid(row=1, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=(10, 0))
        for label in OUTPUT_MODES:
            ttk.Radiobutton(
                mode_frame,
                text=label,
                value=label,
                variable=self.output_mode_label_var,
            ).pack(side="left", padx=(0, 14))

        ttk.Label(frame_options, text="SAÍDA", style="Panel.TLabel").grid(row=2, column=0, sticky="nw", pady=(14, 0))
        self.output_format_label_var = tk.StringVar(value="Compatível (MP4, legenda fixa)")
        format_frame = ttk.Frame(frame_options, style="Panel.TFrame")
        format_frame.grid(row=2, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=(10, 0))
        for label in OUTPUT_FORMATS:
            ttk.Radiobutton(
                format_frame,
                text=label,
                value=label,
                variable=self.output_format_label_var,
            ).pack(side="left", padx=(0, 14))

        ttk.Label(frame_options, text="INFERÊNCIA", style="Panel.TLabel").grid(row=3, column=0, sticky="nw", pady=(14, 0))
        self.inference_profile_label_var = tk.StringVar(value="Equilibrado")
        profile_frame = ttk.Frame(frame_options, style="Panel.TFrame")
        profile_frame.grid(row=3, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=(10, 0))
        for label in INFERENCE_PROFILES:
            ttk.Radiobutton(
                profile_frame, text=label, value=label,
                variable=self.inference_profile_label_var,
            ).pack(side="left", padx=(0, 14))

        ttk.Label(frame_options, text="TAMANHO (MP4)", style="Panel.TLabel").grid(row=4, column=0, sticky="nw", pady=(14, 0))
        self.subtitle_size_label_var = tk.StringVar(value="Pequena")
        size_frame = ttk.Frame(frame_options, style="Panel.TFrame")
        size_frame.grid(row=4, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=(10, 0))
        for label in SUBTITLE_SIZES:
            ttk.Radiobutton(
                size_frame, text=label, value=label,
                variable=self.subtitle_size_label_var,
            ).pack(side="left", padx=(0, 14))
        ttk.Label(
            frame_options,
            text="Grátis = inferência local sem reparo extra. Tradução pode usar API quando não existir faixa em português.",
            style="PanelMuted.TLabel",
            wraplength=590,
            justify="left",
        ).grid(row=5, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=(8, 0))

        # Buttons
        frame_buttons = ttk.Frame(root)
        frame_buttons.pack(fill="x", padx=38, pady=(2, 12))

        self.process_btn = ttk.Button(frame_buttons, text="PROCESSAR", command=self.start_processing)
        self.process_btn.pack(side="left", padx=(0, 10))

        self.open_folder_btn = ttk.Button(
            frame_buttons, text="ABRIR PASTA", style="Secondary.TButton",
            command=self.open_project_folder, state="disabled",
        )
        self.open_folder_btn.pack(side="left")

        # Progress
        self.progress = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=38, pady=5)

        self.status_label = ttk.Label(root, text="PRONTO PARA COMEÇAR", style="Muted.TLabel")
        self.status_label.pack(pady=(0, 5))

        # Log area
        ttk.Label(root, text="ATIVIDADE", foreground=muted).pack(anchor="w", padx=38)
        self.log_area = scrolledtext.ScrolledText(
            root, height=12, wrap=tk.WORD, font=("Consolas", 10),
            bg="#070A12", fg="#B9D9E8", insertbackground=cyan,
            selectbackground="#273C5A", borderwidth=0, padx=12, pady=10,
        )
        self.log_area.pack(fill="both", expand=True, padx=38, pady=(5, 22))
        self.log_area.config(state="disabled")

        self.last_output_path = None

    def log(self, text):
        self.log_area.config(state="normal")
        self.log_area.insert("end", text if text.endswith("\n") else text + "\n")
        self.log_area.see("end")
        self.log_area.config(state="disabled")

    def set_status(self, text):
        self.status_label.config(text=text)

    def update_progress(self, percent, status_text):
        """Update progress bar and status label from worker thread."""
        # Tkinter is not thread-safe: schedule the update on the main thread
        self.root.after(0, self._apply_progress, percent, status_text)

    def _apply_progress(self, percent, status_text):
        self.progress['value'] = percent
        self.status_label.config(text=status_text)

    def start_processing(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Link vazio", "Cole um link do YouTube primeiro.")
            return
        if not ("youtube.com" in url or "youtu.be" in url):
            messagebox.showwarning("Link inválido", "Cole um link válido do YouTube.")
            return

        resolution = self.res_var.get()
        target_language = self.lang_var.get()
        subtitle_mode_label = self.output_mode_label_var.get()
        subtitle_mode = OUTPUT_MODES[subtitle_mode_label]
        output_format_label = self.output_format_label_var.get()
        output_format = OUTPUT_FORMATS[output_format_label]
        profile_label = self.inference_profile_label_var.get()
        inference_profile = INFERENCE_PROFILES[profile_label]
        subtitle_size_label = self.subtitle_size_label_var.get()
        subtitle_scale = SUBTITLE_SIZES[subtitle_size_label]

        self.process_btn.config(state="disabled")
        self.open_folder_btn.config(state="disabled")
        self.progress['value'] = 0
        self.set_status(
            f"{resolution}p  //  {profile_label}  //  {subtitle_mode_label}  //  {output_format_label}"
        )
        self.log_area.config(state="normal")
        self.log_area.delete("1.0", "end")
        self.log_area.config(state="disabled")
        self.last_output_path = None

        thread = threading.Thread(
            target=run_processing,
            args=(url, resolution, target_language, self.log,
                  self.on_done, self.on_error, self.update_progress, subtitle_mode,
                  output_format, inference_profile, subtitle_scale),
            daemon=True,
        )
        thread.start()

    def on_done(self, output_path, usage_summary):
        self.last_output_path = output_path
        self.root.after(0, self._finish_success, output_path, usage_summary)

    def _finish_success(self, output_path, usage_summary):
        self.progress['value'] = 100
        usage_text = format_api_usage(usage_summary)
        cost_line = usage_text.splitlines()[0]
        self.set_status(f"Pronto — {cost_line}")
        self.log(f"\n✅ Vídeo salvo em: {output_path}\n{usage_text}")
        self.process_btn.config(state="normal")
        self.open_folder_btn.config(state="normal")
        messagebox.showinfo(
            "Concluído",
            f"Vídeo processado com sucesso!\n\n{output_path}\n\n{usage_text}",
        )

    def on_error(self, error_msg):
        self.root.after(0, self._finish_error, error_msg)

    def _finish_error(self, error_msg):
        self.progress['value'] = 0
        self.set_status("Erro no processamento")
        self.log(f"\n❌ ERRO: {error_msg}\n")
        self.process_btn.config(state="normal")
        messagebox.showerror("Erro", error_msg)

    def open_project_folder(self):
        path = self.last_output_path or str(PROJECT_DIR)
        os.startfile(str(Path(path).parent))


def main():
    migrate_legacy_api_key()
    root = tk.Tk()
    app = VideoLingoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
