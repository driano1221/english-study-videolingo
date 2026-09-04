"""Small, dependency-free audit gate for a publishable repository."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "LICENSE",
    "NOTICE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/project/architecture.md",
    "docs/project/operations.md",
    "docs/project/repository-map.md",
    "docs/project/validation.md",
    "docs/project/references.md",
)
FORBIDDEN_PARTS = {".venv", ".venv312", "output", "_model_cache", "__pycache__"}
FORBIDDEN_NAMES = {".env", "config.backup.yaml"}
MAX_TRACKED_BYTES = 50 * 1024 * 1024
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
SECRET_VALUE = re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,})")


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def config_api_key_is_empty() -> bool:
    lines = (ROOT / "config.yaml").read_text(encoding="utf-8").splitlines()
    in_api = False
    for line in lines:
        if line and not line.startswith((" ", "#")):
            in_api = line.rstrip() == "api:"
            continue
        if in_api and line.lstrip().startswith("key:"):
            value = line.split(":", 1)[1].strip().strip("'\"")
            return not value
    return False


def audit() -> list[str]:
    errors: list[str] = []
    for name in REQUIRED:
        if not (ROOT / name).is_file():
            errors.append(f"documento obrigatório ausente: {name}")

    files = repository_files()
    for path in files:
        relative = path.relative_to(ROOT)
        if FORBIDDEN_PARTS.intersection(relative.parts):
            errors.append(f"artefato local versionado: {relative}")
        if relative.name in FORBIDDEN_NAMES:
            errors.append(f"arquivo sensível versionado: {relative}")
        if path.is_file() and path.stat().st_size > MAX_TRACKED_BYTES:
            errors.append(f"arquivo versionado maior que 50 MiB: {relative}")
        if path.is_file() and path.stat().st_size < 2 * 1024 * 1024:
            content = path.read_bytes()
            if b"C:\\Users\\" in content:
                errors.append(f"caminho de usuário absoluto no repositório: {relative}")
            if SECRET_VALUE.search(content):
                errors.append(f"possível segredo no repositório: {relative}")

        if path.suffix.lower() == ".md":
            text = path.read_text(encoding="utf-8")
            for target in MARKDOWN_LINK.findall(text):
                clean = target.strip().strip("<>").split("#", 1)[0]
                if not clean or clean.startswith(("/", "#", "http://", "https://", "mailto:")):
                    continue
                if not (path.parent / clean).exists():
                    errors.append(f"link Markdown quebrado em {relative}: {clean}")

    if not config_api_key_is_empty():
        errors.append("config.yaml deve manter api.key vazio")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", action="store_true", help="executa unittest após a auditoria")
    args = parser.parse_args()

    errors = audit()
    if errors:
        for error in errors:
            print(f"[ERRO] {error}")
        return 1
    print("[OK] estrutura, arquivos rastreados e configuração pública")

    if args.tests:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            cwd=ROOT,
        )
        if result.returncode:
            return result.returncode
        print("[OK] testes automatizados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
