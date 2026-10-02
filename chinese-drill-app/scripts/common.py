#!/usr/bin/env python3
"""Shared helpers for the Chinese drill content pipeline."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
COLLECTION_ROOT = Path(
    os.environ.get("CHINESE_DRILL_COLLECTION_DIR", str(PROJECT_ROOT))
).expanduser().resolve()
DATA_DIR = COLLECTION_ROOT / "data"
BUILD_DIR = COLLECTION_ROOT / "build"
DIST_DIR = COLLECTION_ROOT / "dist"
AUDIO_DIR = COLLECTION_ROOT / "audio"
GENERATED_DIR = DATA_DIR / "generated"
SCHEMA_DIR = PROJECT_ROOT / "schemas"
PROMPT_DIR = PROJECT_ROOT / "prompts"


def load_dotenv(path: Path | None = None) -> None:
    """Load a small KEY=VALUE dotenv file without replacing exported values."""
    dotenv_path = path or COLLECTION_ROOT / ".env"
    if not dotenv_path.is_file() and path is None:
        dotenv_path = PROJECT_ROOT / ".env"
    if not dotenv_path.is_file():
        return

    for line_number, raw_line in enumerate(
        dotenv_path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise ValueError(
                f"Invalid .env entry on line {line_number}: expected KEY=VALUE"
            )

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid .env key on line {line_number}")

        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()

        os.environ.setdefault(key, value)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Required file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error


def atomic_write_json(path: Path, value: Any) -> None:
    """Write JSON atomically so interrupted pipeline runs keep prior output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def source_configuration() -> tuple[Path, dict[str, Any]]:
    config = read_json(DATA_DIR / "sources.json")
    source_directory = (DATA_DIR / config["source_directory"]).resolve()
    if not source_directory.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_directory}")
    return source_directory, config


def lesson_paths(lesson: str) -> tuple[Path, Path]:
    source_directory, config = source_configuration()
    transcript = source_directory / f"{lesson}{config['transcript_suffix']}"
    analysis = source_directory / f"{lesson}{config['analysis_suffix']}"
    if not transcript.is_file() and not config.get("transcript_optional", False):
        raise FileNotFoundError(f"Transcript not found: {transcript}")
    if not analysis.is_file():
        raise FileNotFoundError(f"Analysis not found: {analysis}")
    return transcript, analysis


def selected_lessons(requested: list[str] | None = None) -> list[str]:
    _, config = source_configuration()
    lessons = list(config["lessons"])
    if not requested:
        return lessons

    unknown = sorted(set(requested) - set(lessons))
    if unknown:
        raise ValueError(f"Unknown lesson date(s): {', '.join(unknown)}")
    requested_set = set(requested)
    return [lesson for lesson in lessons if lesson in requested_set]


def normalize_chinese(text: str) -> str:
    """Return a stable key for exact-sentence deduplication."""
    return re.sub(r"[\s，。！？、；：,.!?;:\"'“”‘’（）()]", "", text)


def sentence_id(chinese: str) -> str:
    import hashlib

    digest = hashlib.sha256(normalize_chinese(chinese).encode("utf-8")).hexdigest()
    return f"sentence-{digest[:12]}"


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    result = [require_string(item, f"{field}[]") for item in value]
    return list(dict.fromkeys(result))
