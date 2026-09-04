import os
import gc
import json
import warnings
import time
import subprocess
import torch
import functools
from pathlib import Path

warnings.filterwarnings("ignore")

# =============================================================================
# Compatibility shim — applied BEFORE importing whisperx
# =============================================================================

# torch.load: default weights_only=False for pyannote checkpoints
# PyTorch >=2.6 changed torch.load default to weights_only=True.
# pyannote checkpoints contain omegaconf objects that fail the safety check.
# Monkey-patch torch.load to default to weights_only=False (matching <2.6
# behavior).  This is safe here because all model files come from trusted
# sources (HuggingFace / pyannote).
_original_torch_load = torch.load
@functools.wraps(_original_torch_load)
def _patched_torch_load(*args, **kwargs):
    if kwargs.get("weights_only") is None:
        kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

# =============================================================================
# Now safe to import whisperx and the rest of the application
# =============================================================================
import whisperx
from whisperx.audio import load_audio as _whisperx_load_audio, SAMPLE_RATE as _WHISPERX_SR
from rich import print as rprint
from core.utils import *
from core.asr_backend.runtime_utils import (
    hotwords_from_metadata,
    profile_settings,
    run_batch_fallback,
    speech_gap_candidates,
)
MODEL_DIR = load_key("model_dir")


def _hf_cache_dir_for_repo(cache_root, repo_id):
    return Path(cache_root) / f"models--{repo_id.replace('/', '--')}"


def _has_complete_hf_snapshot(cache_root, repo_id):
    repo_dir = _hf_cache_dir_for_repo(cache_root, repo_id)
    snapshots = repo_dir / "snapshots"
    if not snapshots.exists():
        return False
    required_files = {"config.json", "model.bin", "tokenizer.json"}
    for snapshot in snapshots.iterdir():
        if snapshot.is_dir() and all((snapshot / name).exists() for name in required_files):
            return True
    return False

@functools.lru_cache(maxsize=1)
@except_handler("failed to check hf mirror", default_return=None)
def check_hf_mirror():
    mirrors = {'Official': 'huggingface.co', 'Mirror': 'hf-mirror.com'}
    fastest_url = f"https://{mirrors['Official']}"
    best_time = float('inf')
    rprint("[cyan]🔍 Checking HuggingFace mirrors...[/cyan]")
    for name, domain in mirrors.items():
        if os.name == 'nt':
            cmd = ['ping', '-n', '1', '-w', '3000', domain]
        else:
            cmd = ['ping', '-c', '1', '-W', '3', domain]
        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        response_time = time.time() - start
        if result.returncode == 0:
            if response_time < best_time:
                best_time = response_time
                fastest_url = f"https://{domain}"
            rprint(f"[green]✓ {name}:[/green] {response_time:.2f}s")
    if best_time == float('inf'):
        rprint("[yellow]⚠️ All mirrors failed, using default[/yellow]")
    rprint(f"[cyan]🚀 Selected mirror:[/cyan] {fastest_url} ({best_time:.2f}s)")
    return fastest_url

def _job_metadata(path="output/.videolingo_job.json"):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


class WhisperSession:
    """Own one model, aligner and pair of decoded audio arrays per media."""

    def __init__(self, raw_audio_file, vocal_audio_file, profile="balanced"):
        self.raw_audio_file = raw_audio_file
        self.vocal_audio_file = vocal_audio_file
        self.settings = profile_settings(profile)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_type = "int8_float16" if self.device == "cuda" else "int8"
        self.requested_language = load_key("whisper.language")
        self.batch_size = None
        self.model = None
        self.align_model = None
        self.align_metadata = None
        self.align_language = None
        self.raw_audio = None
        self.vocal_audio = None
        self.stats = {
            "profile": self.settings["name"],
            "device": self.device,
            "compute_type": self.compute_type,
            "model_loads": 0,
            "aligner_loads": 0,
            "audio_loads": 0,
            "batch_attempts": [],
            "gap_candidates": 0,
            "gaps_repaired": 0,
        }

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False

    def load(self):
        if self.model is not None:
            return self
        endpoint = check_hf_mirror()
        if endpoint:
            os.environ["HF_ENDPOINT"] = endpoint
        model_name, download_root = self._model_location()
        hotwords = hotwords_from_metadata(_job_metadata())
        asr_options = {
            "temperatures": [0],
            "initial_prompt": hotwords or None,
            "hotwords": hotwords or None,
        }
        language = None if "auto" in self.requested_language else self.requested_language
        kwargs = {
            "device": self.device,
            "compute_type": self.compute_type,
            "language": language,
            "vad_options": {
                "vad_onset": self.settings["vad_onset"],
                "vad_offset": self.settings["vad_offset"],
            },
            "asr_options": asr_options,
        }
        if download_root:
            kwargs["download_root"] = download_root
        rprint(
            f"[cyan]WhisperX: {self.device}, {self.compute_type}, "
            f"perfil {self.settings['label']}.[/cyan]"
        )
        if hotwords:
            rprint(f"[cyan]Hotwords do vídeo:[/cyan] {hotwords}")
        self.model = whisperx.load_model(model_name, **kwargs)
        self.stats["model_loads"] += 1
        self.raw_audio = _whisperx_load_audio(self.raw_audio_file, sr=_WHISPERX_SR)
        self.stats["audio_loads"] += 1
        try:
            same_audio = os.path.samefile(self.raw_audio_file, self.vocal_audio_file)
        except OSError:
            same_audio = self.raw_audio_file == self.vocal_audio_file
        if same_audio:
            self.vocal_audio = self.raw_audio
        else:
            self.vocal_audio = _whisperx_load_audio(self.vocal_audio_file, sr=_WHISPERX_SR)
            self.stats["audio_loads"] += 1
        return self

    def _model_location(self):
        download_root = MODEL_DIR
        if self.requested_language == "zh":
            model_name = "Huan69/Belle-whisper-large-v3-zh-punct-fasterwhisper"
            local_model = os.path.join(MODEL_DIR, "Belle-whisper-large-v3-zh-punct-fasterwhisper")
        else:
            model_name = load_key("whisper.model")
            local_model = os.path.join(MODEL_DIR, model_name)
        if os.path.exists(local_model):
            return local_model, None
        repo_id = model_name if "/" in model_name else f"Systran/faster-whisper-{model_name}"
        if not _has_complete_hf_snapshot(MODEL_DIR, repo_id):
            download_root = None
        return model_name, download_root

    @staticmethod
    def _slice(audio, start, end):
        return audio[int(start * _WHISPERX_SR):int(end * _WHISPERX_SR)]

    def _transcribe(self, audio):
        batches = (self.batch_size,) if self.batch_size else (4, 2, 1)

        def call(batch):
            self.stats["batch_attempts"].append(batch)
            rprint(f"[cyan]Testando batch {batch}...[/cyan]")
            return self.model.transcribe(audio, batch_size=batch, print_progress=True)

        try:
            result, winner = run_batch_fallback(call, batches)
        except Exception:
            if self.batch_size in (4, 2):
                smaller = tuple(value for value in (2, 1) if value < self.batch_size)
                result, winner = run_batch_fallback(call, smaller)
            else:
                raise
        self.batch_size = winner
        self.stats["selected_batch"] = winner
        return result

    def _ensure_aligner(self, language):
        if self.align_model is not None and self.align_language == language:
            return
        if self.align_model is not None:
            del self.align_model
            torch.cuda.empty_cache()
        self.align_model, self.align_metadata = whisperx.load_align_model(
            language_code=language, device=self.device
        )
        self.align_language = language
        self.stats["aligner_loads"] += 1

    def transcribe_range(self, start, end):
        self.load()
        rprint(f"[green]WhisperX: {start:.2f}s → {end:.2f}s[/green]")
        raw = self._slice(self.raw_audio, start, end)
        vocal = self._slice(self.vocal_audio, start, end)
        transcribe_started = time.perf_counter()
        result = self._transcribe(raw)
        self.stats["transcribe_seconds"] = round(
            self.stats.get("transcribe_seconds", 0) + time.perf_counter() - transcribe_started, 3
        )
        language = result["language"]
        if self.stats.get("language") is None:
            self.stats["language"] = language
            update_key("whisper.language", language)
        if language == "zh" and self.requested_language != "zh":
            raise ValueError("Please specify the transcription language as zh and try again!")
        self._ensure_aligner(language)
        align_started = time.perf_counter()
        result = whisperx.align(
            result["segments"], self.align_model, self.align_metadata, vocal,
            self.device, return_char_alignments=False,
        )
        self.stats["align_seconds"] = round(
            self.stats.get("align_seconds", 0) + time.perf_counter() - align_started, 3
        )
        for segment in result["segments"]:
            segment["start"] += start
            segment["end"] += start
            for word in segment.get("words", []):
                if "start" in word:
                    word["start"] += start
                if "end" in word:
                    word["end"] += start
        return result

    def repair_gaps(self, result):
        gaps = speech_gap_candidates(
            result.get("segments", []), self.raw_audio, _WHISPERX_SR, self.settings
        )
        self.stats["gap_candidates"] = len(gaps)
        repairs = []
        for gap in gaps:
            repaired = self.transcribe_range(max(0, gap["start"] - 0.15), gap["end"] + 0.15)
            words = []
            for segment in repaired.get("segments", []):
                for word in segment.get("words", []):
                    midpoint = (float(word.get("start", 0)) + float(word.get("end", 0))) / 2
                    if gap["start"] <= midpoint <= gap["end"] and str(word.get("word", "")).strip():
                        words.append(word)
            if words:
                repairs.append(
                    {
                        "start": words[0]["start"],
                        "end": words[-1]["end"],
                        "text": " ".join(str(word["word"]).strip() for word in words),
                        "words": words,
                        "gap_repair": True,
                    }
                )
        result["segments"].extend(repairs)
        result["segments"].sort(key=lambda segment: float(segment.get("start", 0)))
        self.stats["gaps_repaired"] = len(repairs)
        return result

    def write_stats(self, path="output/log/asr_runtime.json"):
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.stats, ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self):
        self.write_stats()
        self.model = self.align_model = self.raw_audio = self.vocal_audio = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


@except_handler("WhisperX processing error:")
def transcribe_audio(raw_audio_file, vocal_audio_file, start, end, profile="balanced"):
    """Compatibility wrapper; the main pipeline uses one shared session."""
    with WhisperSession(raw_audio_file, vocal_audio_file, profile) as session:
        return session.transcribe_range(start, end)
