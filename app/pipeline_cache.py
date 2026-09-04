"""Content-addressed cache and resumable active workspace for the simple GUI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse


CACHE_SCHEMA_VERSION = 1
METADATA_NAME = ".videolingo_job.json"
MEDIA_METADATA_NAME = "media.json"
FINAL_RENDER_NAMES = {"output_sub.mp4", "output_sub.mkv"}
_SECRET_LINE = re.compile(
    r"^\s*(?:key|api_key|access_token|secret|password|whisperX_302_api_key|elevenlabs_api_key)\s*:",
    re.IGNORECASE,
)
_RUNTIME_ONLY_LINE = re.compile(
    r"^\s*(?:max_workers|ffmpeg_gpu|ytb_resolution|timeout_seconds|max_retries|max_cost_usd|"
    r"input_cost_per_million(?:_off_peak|_peak)?|cached_input_cost_per_million(?:_off_peak|_peak)?|"
    r"output_cost_per_million(?:_off_peak|_peak)?)\s*:",
    re.IGNORECASE,
)


def normalize_source(url: str) -> str:
    """Return a stable YouTube identity, falling back to a normalized URL."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
        if video_id:
            return f"youtube:{video_id}"
    if host.endswith("youtube.com"):
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if video_id:
            return f"youtube:{video_id}"
    return url.strip()


def config_fingerprint(config_path: Path) -> str:
    """Hash behavior-affecting config without including credentials."""
    if not config_path.is_file():
        return "missing-config"
    safe_lines = []
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if _SECRET_LINE.match(line) or _RUNTIME_ONLY_LINE.match(line):
            continue
        safe_lines.append(line.rstrip())
    return hashlib.sha256("\n".join(safe_lines).encode("utf-8")).hexdigest()


def build_job_id(
    url: str,
    resolution: str,
    target_language: str,
    config_path: Path,
    inference_profile: str = "balanced",
) -> str:
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "source": normalize_source(url),
        "resolution": str(resolution),
        "target_language": target_language,
        "inference_profile": inference_profile,
        "config": config_fingerprint(config_path),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    source_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", payload["source"]).strip("-")[-40:]
    return f"{source_slug or 'media'}-{digest}"


class JobCache:
    def __init__(self, active_output: Path, cache_root: Path):
        self.active_output = active_output.resolve()
        self.cache_root = cache_root.resolve()
        self.jobs_root = self.cache_root / "jobs"
        self.media_root = self.cache_root / "media"
        self.legacy_root = self.cache_root / "legacy"

    def _assert_managed_path(self, path: Path, parent: Path) -> None:
        resolved = path.resolve()
        if resolved == parent.resolve() or parent.resolve() not in resolved.parents:
            raise RuntimeError(f"Refusing unsafe cache operation outside {parent}: {resolved}")

    def _read_metadata(self, folder: Path) -> dict:
        path = folder / METADATA_NAME
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def active_metadata(self) -> dict:
        return self._read_metadata(self.active_output)

    def _write_metadata(self, folder: Path, metadata: dict) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / METADATA_NAME
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def _has_payload(self, folder: Path) -> bool:
        return folder.is_dir() and any(p.name != METADATA_NAME for p in folder.iterdir())

    def _clear_active(self) -> None:
        if not self.active_output.exists():
            return
        self._assert_managed_path(self.active_output, self.active_output.parent)
        shutil.rmtree(self.active_output)

    def _copy_snapshot(self, source: Path, destination: Path, ignored_names=()) -> None:
        self._assert_managed_path(destination, self.cache_root)
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns(*ignored_names) if ignored_names else None,
        )

    @staticmethod
    def _media_key(source: str, resolution: str) -> str:
        value = f"{normalize_source(source)}\n{resolution}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _manifest_media(folder: Path) -> tuple[Path, str] | None:
        manifest = folder / "input_manifest.json"
        if not manifest.is_file():
            return None
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            media_type = payload.get("type")
            name = Path(str(payload.get("path", "")).replace("\\", "/")).name
            candidate = folder / name
            if media_type in {"video", "audio"} and candidate.is_file():
                return candidate, media_type
        except (OSError, ValueError, TypeError):
            return None
        return None

    @staticmethod
    def _link_or_copy(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination.unlink()
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)

    def _store_media(self, folder: Path, metadata: dict) -> tuple[dict, Path] | None:
        found = self._manifest_media(folder)
        if not found:
            return None
        source_file, media_type = found
        media_key = self._media_key(metadata.get("source", ""), metadata.get("resolution", ""))
        media_dir = self.media_root / media_key
        media_info_path = media_dir / MEDIA_METADATA_NAME
        media_info = self._read_metadata_file(media_info_path)
        canonical = media_dir / str(media_info.get("filename", source_file.name))
        if not canonical.is_file() or canonical.stat().st_size != source_file.stat().st_size:
            media_dir.mkdir(parents=True, exist_ok=True)
            canonical = media_dir / source_file.name
            self._link_or_copy(source_file, canonical)
            media_info = {
                "key": media_key,
                "source": metadata.get("source", ""),
                "resolution": str(metadata.get("resolution", "")),
                "filename": canonical.name,
                "type": media_type,
                "size": canonical.stat().st_size,
            }
            self._write_json_atomic(media_info_path, media_info)
        metadata.update(
            media_key=media_key,
            media_name=canonical.name,
            media_type=media_type,
            media_size=canonical.stat().st_size,
        )
        if source_file.resolve() != canonical.resolve():
            try:
                already_shared = os.path.samefile(source_file, canonical)
            except OSError:
                already_shared = False
            if not already_shared:
                replacement = source_file.with_name(source_file.name + ".shared.tmp")
                self._link_or_copy(canonical, replacement)
                replacement.replace(source_file)
        return media_info, canonical

    @staticmethod
    def _read_metadata_file(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def _restore_media(self, folder: Path, *, source: str, resolution: str) -> bool:
        key = self._media_key(source, resolution)
        media_dir = self.media_root / key
        info = self._read_metadata_file(media_dir / MEDIA_METADATA_NAME)
        canonical = media_dir / str(info.get("filename", ""))
        if not canonical.is_file() or canonical.stat().st_size < 1:
            return False
        destination = folder / canonical.name
        self._link_or_copy(canonical, destination)
        self._write_json_atomic(
            folder / "input_manifest.json",
            {"path": f"output/{canonical.name}", "type": info.get("type", "video")},
        )
        metadata = self._read_metadata(folder)
        metadata.update(
            media_key=key,
            media_name=canonical.name,
            media_type=info.get("type", "video"),
            media_size=canonical.stat().st_size,
        )
        self._write_metadata(folder, metadata)
        return True

    def ensure_free_space(self, resolution: str) -> dict:
        required_gib = {"360": 1, "480": 2, "720": 3, "1080": 4, "best": 5}.get(
            str(resolution), 4
        )
        usage = shutil.disk_usage(self.cache_root.parent)
        required = required_gib * 1024**3
        if usage.free < required:
            raise RuntimeError(
                f"Espaço insuficiente: {usage.free / 1024**3:.1f} GB livres; "
                f"reserve pelo menos {required_gib} GB para processar em {resolution}p."
            )
        return {"free_bytes": usage.free, "required_bytes": required}

    def save_active(self) -> Path | None:
        if not self._has_payload(self.active_output):
            return None
        metadata = self.active_metadata()
        job_id = metadata.get("job_id")
        if not job_id:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            destination = self.legacy_root / stamp
            metadata = {
                "schema": CACHE_SCHEMA_VERSION,
                "job_id": f"legacy-{stamp}",
                "legacy": True,
            }
            self._write_metadata(self.active_output, metadata)
        else:
            destination = self.jobs_root / str(job_id)
        stored_media = self._store_media(self.active_output, metadata)
        metadata["saved_at"] = datetime.now(timezone.utc).isoformat()
        self._write_metadata(self.active_output, metadata)
        ignored = set(FINAL_RENDER_NAMES)
        if stored_media:
            ignored.add(stored_media[1].name)
        self._copy_snapshot(self.active_output, destination, ignored)
        return destination

    def prepare(self, job_id: str, *, url: str, resolution: str, target_language: str) -> bool:
        """Activate a job. Return True when cached artifacts were restored/reused."""
        current = self.active_metadata()
        if current.get("job_id") == job_id and self.active_output.is_dir():
            self._store_media(self.active_output, current)
            current["last_opened_at"] = datetime.now(timezone.utc).isoformat()
            self._write_metadata(self.active_output, current)
            return self._has_payload(self.active_output)

        if self._has_payload(self.active_output):
            self.save_active()
        self._clear_active()

        snapshot = self.jobs_root / job_id
        restored_job = snapshot.is_dir()
        if restored_job:
            shutil.copytree(snapshot, self.active_output)
        else:
            self.active_output.mkdir(parents=True, exist_ok=True)

        restored_media = self._restore_media(
            self.active_output,
            source=normalize_source(url),
            resolution=str(resolution),
        )

        metadata = self.active_metadata()
        metadata.update(
            {
                "schema": CACHE_SCHEMA_VERSION,
                "job_id": job_id,
                "source": normalize_source(url),
                "url": url,
                "resolution": str(resolution),
                "target_language": target_language,
                "last_opened_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write_metadata(self.active_output, metadata)
        return restored_job or restored_media

    def compact_existing_jobs(self) -> dict:
        """Move raw media into the shared store and drop useless cached renders."""
        jobs = 0
        bytes_removed = 0
        if not self.jobs_root.is_dir():
            return {"jobs": 0, "bytes_removed": 0}
        for folder in self.jobs_root.iterdir():
            if not folder.is_dir():
                continue
            metadata = self._read_metadata(folder)
            stored = self._store_media(folder, metadata)
            if stored:
                source_file = self._manifest_media(folder)
                canonical = stored[1]
                if source_file and source_file[0] != canonical:
                    bytes_removed += source_file[0].stat().st_size
                    source_file[0].unlink()
                self._write_json_atomic(
                    folder / "input_manifest.json",
                    {"path": f"output/{canonical.name}", "type": stored[0].get("type", "video")},
                )
            for name in FINAL_RENDER_NAMES:
                rendered = folder / name
                if rendered.is_file():
                    bytes_removed += rendered.stat().st_size
                    rendered.unlink()
            self._write_metadata(folder, metadata)
            jobs += 1
        return {"jobs": jobs, "bytes_removed": bytes_removed}

    def update_active_metadata(self, **updates) -> dict:
        metadata = self.active_metadata()
        metadata.update(updates)
        self._write_metadata(self.active_output, metadata)
        return metadata
