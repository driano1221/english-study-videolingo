"""Small, dependency-free metrics recorder for one VideoLingo run."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


TIMESTAMP = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _process_ram_mib() -> float | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        handle = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return round(counters.WorkingSetSize / 1024**2, 2)
    except (AttributeError, OSError):
        pass
    return None


def _nvidia_vram_mib() -> float | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            values = [float(line.strip()) for line in result.stdout.splitlines() if line.strip()]
            return max(values) if values else None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


class ResourceSampler:
    def __init__(self, interval=1.0):
        self.interval = interval
        self.samples = 0
        self.peak_ram_mib = 0.0
        self.peak_nvidia_vram_mib = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        self._thread.join(timeout=self.interval + 5)
        return {
            "samples": self.samples,
            "peak_process_ram_mib": self.peak_ram_mib or None,
            "peak_nvidia_vram_mib": self.peak_nvidia_vram_mib or None,
            "vram_note": "Uso total da GPU NVIDIA; inclui outros processos ativos.",
        }

    def _loop(self):
        while not self._stop.is_set():
            ram = _process_ram_mib()
            vram = _nvidia_vram_mib()
            self.samples += 1
            if ram is not None:
                self.peak_ram_mib = max(self.peak_ram_mib, ram)
            if vram is not None:
                self.peak_nvidia_vram_mib = max(self.peak_nvidia_vram_mib, vram)
            self._stop.wait(self.interval)


def _seconds(value: str) -> float:
    match = TIMESTAMP.fullmatch(value.strip())
    if not match:
        raise ValueError(value)
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms")) / 1000
    )


def subtitle_coverage(path: str | Path, media_duration: float) -> dict:
    """Measure union of SRT cue intervals over the complete media timeline."""
    intervals = []
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
        for line in text.splitlines():
            if "-->" not in line:
                continue
            start, end = (_seconds(part) for part in line.split("-->", 1))
            if end > start:
                intervals.append((max(0.0, start), min(float(media_duration), end)))
    except (OSError, ValueError):
        intervals = []
    intervals.sort()
    merged = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    covered = sum(max(0.0, end - start) for start, end in merged)
    duration = max(0.0, float(media_duration or 0))
    return {
        "subtitle_file": str(path),
        "cue_count": len(intervals),
        "timeline_covered_seconds": round(covered, 3),
        "timeline_uncovered_seconds": round(max(0.0, duration - covered), 3),
        "timeline_coverage_ratio": round(covered / duration, 6) if duration else None,
        "coverage_note": "Cobertura da linha do tempo, incluindo pausas sem fala.",
    }


class RunMetrics:
    def __init__(self, path="output/log/run_metrics.json", sample_interval=1.0):
        self.path = Path(path)
        self.data = {"schema": 1, "started_at": _iso_now(), "stages": {}}
        self._start = time.perf_counter()
        self._sampler = ResourceSampler(sample_interval)
        self._finished = False

    def __enter__(self):
        self._sampler.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.finish("error" if exc else "completed", str(exc) if exc else None)
        return False

    @contextmanager
    def stage(self, name: str):
        started = time.perf_counter()
        record = {"started_at": _iso_now()}
        self.data["stages"][name] = record
        try:
            yield record
        except Exception:
            record["status"] = "error"
            raise
        else:
            record["status"] = "completed"
        finally:
            record["elapsed_seconds"] = round(time.perf_counter() - started, 3)

    def stage_seconds(self, name: str) -> float:
        return float(self.data["stages"].get(name, {}).get("elapsed_seconds", 0))

    def record(self, **values):
        self.data.update(values)

    def finish(self, status="completed", error=None):
        if self._finished:
            return
        self._finished = True
        self.data.update(
            status=status,
            finished_at=_iso_now(),
            total_elapsed_seconds=round(time.perf_counter() - self._start, 3),
            resources=self._sampler.stop(),
        )
        if error:
            self.data["error"] = error
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
