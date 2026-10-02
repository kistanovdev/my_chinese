#!/usr/bin/env python3
"""Launch the local Chinese sentence drill app with no web framework."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import tempfile
import threading
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_DIRECTORY = PROJECT_ROOT / "web"
AUDIO_DIRECTORY = PROJECT_ROOT / "audio"
COLLECTION_AUDIO_DIRECTORIES = {
    "berlitz3": PROJECT_ROOT / "collections" / "berlitz3" / "audio",
    "berlitz4": PROJECT_ROOT / "collections" / "berlitz4" / "audio",
}
DECK_PATH = PROJECT_ROOT / "dist" / "deck.json"
DEFAULT_PROGRESS_PATH = PROJECT_ROOT / "data" / "progress.json"
MAX_PROGRESS_BYTES = 2_000_000
MAX_RECORDING_BYTES = 10_000_000
MAX_RECORDING_DURATION_MS = 60_000
RECORDING_MIME_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
}
STATIC_FILES = {
    "/": WEB_DIRECTORY / "index.html",
    "/index.html": WEB_DIRECTORY / "index.html",
    "/styles.css": WEB_DIRECTORY / "styles.css",
    "/app.js": WEB_DIRECTORY / "app.js",
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Required file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary_path = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def default_progress() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "settings": {
            "session_size": 10,
            "repetitions": 3,
            "playback_speed": 1.0,
            "voice_mode": "original",
            "record_after_sequence": True,
        },
        "stats": {
            "total_reviews": 0,
            "sessions_completed": 0,
            "last_session": None,
        },
        "cards": {},
    }


def resolve_audio_path(audio_url: Any, audio_directory: Path) -> Path:
    if not isinstance(audio_url, str) or not audio_url.startswith("/audio/"):
        raise ValueError("Invalid audio path")
    relative = audio_url.removeprefix("/audio/")
    parts = relative.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError("Invalid audio path")
    if len(parts) == 1:
        directory = audio_directory
        filename = parts[0]
    elif len(parts) == 2 and parts[0] in COLLECTION_AUDIO_DIRECTORIES:
        directory = COLLECTION_AUDIO_DIRECTORIES[parts[0]]
        filename = parts[1]
    else:
        raise ValueError("Invalid audio path")
    if Path(filename).name != filename or not filename.endswith(".mp3"):
        raise ValueError("Invalid audio path")
    return directory / filename


def default_recordings_index() -> dict[str, Any]:
    return {"version": 1, "attempts": []}


def normalize_recording_mime_type(value: Any) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError("Recording Content-Type is required")
    mime_type = value.split(";", 1)[0].strip().lower()
    extension = RECORDING_MIME_EXTENSIONS.get(mime_type)
    if extension is None:
        raise ValueError("Unsupported recording format")
    return mime_type, extension


def validate_recordings_index(
    value: Any, deck_ids: set[str], recordings_directory: Path
) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Recordings index must be a version 1 JSON object")
    attempts = value.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("Recordings index attempts must be a list")
    seen_ids: set[str] = set()
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError("Every recording attempt must be an object")
        attempt_id = attempt.get("id")
        if not isinstance(attempt_id, str) or not re.fullmatch(
            r"recording-[0-9TZ]{16}-[0-9a-f]{12}", attempt_id
        ):
            raise ValueError("Recording attempt has an invalid ID")
        if attempt_id in seen_ids:
            raise ValueError(f"Duplicate recording ID: {attempt_id}")
        seen_ids.add(attempt_id)
        sentence_id = attempt.get("sentence_id")
        if sentence_id not in deck_ids:
            raise ValueError(f"Recording references unknown sentence: {sentence_id}")
        mime_type, extension = normalize_recording_mime_type(attempt.get("mime_type"))
        filename = attempt.get("file")
        if filename != f"{attempt_id}{extension}":
            raise ValueError(f"Recording {attempt_id} has an invalid filename")
        if not _valid_timestamp(attempt.get("created_at")):
            raise ValueError(f"Recording {attempt_id} has an invalid timestamp")
        duration_ms = attempt.get("duration_ms")
        size_bytes = attempt.get("size_bytes")
        if not _is_nonnegative_integer(duration_ms) or duration_ms > MAX_RECORDING_DURATION_MS:
            raise ValueError(f"Recording {attempt_id} has an invalid duration")
        if not _is_nonnegative_integer(size_bytes) or not 128 <= size_bytes <= MAX_RECORDING_BYTES:
            raise ValueError(f"Recording {attempt_id} has an invalid size")
        recording_path = recordings_directory / filename
        if not recording_path.is_file() or recording_path.stat().st_size != size_bytes:
            raise ValueError(f"Recording file is missing or incomplete: {filename}")
        attempt["mime_type"] = mime_type
    return value


def validate_deck(
    value: Any, audio_directory: Path = AUDIO_DIRECTORY
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Deck must be a JSON object")
    sentences = value.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        raise ValueError("Deck must contain at least one sentence")

    ids: set[str] = set()
    missing_audio: list[str] = []
    for index, sentence in enumerate(sentences, start=1):
        if not isinstance(sentence, dict):
            raise ValueError(f"Deck sentence {index} must be an object")
        sentence_id = sentence.get("id")
        if not isinstance(sentence_id, str) or not sentence_id:
            raise ValueError(f"Deck sentence {index} has no ID")
        if sentence_id in ids:
            raise ValueError(f"Duplicate deck sentence ID: {sentence_id}")
        ids.add(sentence_id)
        audio_url = sentence.get("audio")
        try:
            audio_path = resolve_audio_path(audio_url, audio_directory)
        except ValueError:
            missing_audio.append(sentence_id)
            continue
        if not audio_path.is_file() or audio_path.stat().st_size < 100:
            missing_audio.append(sentence_id)
        variants = sentence.get("audio_variants", [])
        if variants is not None and not isinstance(variants, list):
            raise ValueError(f"Deck sentence {sentence_id} has invalid audio variants")
        for variant in variants or []:
            if not isinstance(variant, dict):
                raise ValueError(f"Deck sentence {sentence_id} has an invalid audio variant")
            variant_url = variant.get("audio")
            try:
                variant_path = resolve_audio_path(variant_url, audio_directory)
            except ValueError:
                raise ValueError(f"Deck sentence {sentence_id} has an invalid variant path")
            if not variant_path.is_file() or variant_path.stat().st_size < 100:
                raise ValueError(f"Deck sentence {sentence_id} references missing variant audio")

    if missing_audio:
        raise ValueError(
            f"Deck references missing audio for {len(missing_audio)} sentence(s)"
        )
    return value


def _is_nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_timestamp(value: Any, *, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    if not isinstance(value, str) or len(value) > 40:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_progress(value: Any, deck_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Progress must be a version 1 JSON object")

    settings = value.get("settings")
    stats = value.get("stats")
    cards = value.get("cards")
    if not isinstance(settings, dict):
        raise ValueError("Progress settings must be an object")
    if not isinstance(stats, dict):
        raise ValueError("Progress stats must be an object")
    if not isinstance(cards, dict):
        raise ValueError("Progress cards must be an object")

    session_size = settings.get("session_size")
    repetitions = settings.get("repetitions")
    playback_speed = settings.get("playback_speed")
    voice_mode = settings.setdefault("voice_mode", "original")
    record_after_sequence = settings.setdefault("record_after_sequence", True)
    if not isinstance(session_size, int) or not 1 <= session_size <= 50:
        raise ValueError("session_size must be between 1 and 50")
    if repetitions not in (2, 3):
        raise ValueError("repetitions must be 2 or 3")
    if not isinstance(playback_speed, (int, float)) or not 0.75 <= playback_speed <= 1.25:
        raise ValueError("playback_speed must be between 0.75 and 1.25")
    if voice_mode not in {"original", "varied"}:
        raise ValueError("voice_mode must be original or varied")
    if not isinstance(record_after_sequence, bool):
        raise ValueError("record_after_sequence must be a boolean")

    for field in ("total_reviews", "sessions_completed"):
        if not _is_nonnegative_integer(stats.get(field)):
            raise ValueError(f"stats.{field} must be a nonnegative integer")
    if not _valid_timestamp(stats.get("last_session"), nullable=True):
        raise ValueError("stats.last_session must be an ISO timestamp or null")

    allowed_ratings = {"again", "hard", "good", "easy"}
    for sentence_id, card in cards.items():
        if sentence_id not in deck_ids:
            raise ValueError(f"Progress contains unknown sentence ID: {sentence_id}")
        if not isinstance(card, dict):
            raise ValueError(f"Progress card {sentence_id} must be an object")
        for field in ("seen", "box", "streak"):
            if not _is_nonnegative_integer(card.get(field)):
                raise ValueError(f"{sentence_id}.{field} must be nonnegative")
        if card.get("last_rating") not in allowed_ratings:
            raise ValueError(f"{sentence_id}.last_rating is invalid")
        if not _valid_timestamp(card.get("last_reviewed")):
            raise ValueError(f"{sentence_id}.last_reviewed must be an ISO timestamp")
        if not _valid_timestamp(card.get("next_due")):
            raise ValueError(f"{sentence_id}.next_due must be an ISO timestamp")
        ratings = card.get("ratings")
        if not isinstance(ratings, dict):
            raise ValueError(f"{sentence_id}.ratings must be an object")
        for rating in allowed_ratings:
            if not _is_nonnegative_integer(ratings.get(rating)):
                raise ValueError(f"{sentence_id}.ratings.{rating} must be nonnegative")

    value["updated_at"] = utc_timestamp()
    return value


class DrillApplication:
    def __init__(
        self,
        deck_path: Path,
        progress_path: Path,
        audio_directory: Path = AUDIO_DIRECTORY,
        recordings_directory: Path | None = None,
    ):
        self.deck_path = deck_path
        self.progress_path = progress_path
        self.audio_directory = audio_directory
        self.recordings_directory = recordings_directory or progress_path.parent / "recordings"
        self.recordings_index_path = self.recordings_directory / "index.json"
        self.deck = validate_deck(read_json(deck_path), audio_directory)
        self.deck_ids = {sentence["id"] for sentence in self.deck["sentences"]}
        self.lock = threading.Lock()
        if progress_path.exists():
            self.progress = validate_progress(read_json(progress_path), self.deck_ids)
        else:
            self.progress = default_progress()
        if self.recordings_index_path.exists():
            self.recordings = validate_recordings_index(
                read_json(self.recordings_index_path),
                self.deck_ids,
                self.recordings_directory,
            )
        else:
            self.recordings = default_recordings_index()

    def save_progress(self, value: Any) -> dict[str, Any]:
        validated = validate_progress(value, self.deck_ids)
        with self.lock:
            atomic_write_json(self.progress_path, validated)
            self.progress = validated
        return validated

    @staticmethod
    def public_recording(attempt: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": attempt["id"],
            "sentence_id": attempt["sentence_id"],
            "created_at": attempt["created_at"],
            "duration_ms": attempt["duration_ms"],
            "mime_type": attempt["mime_type"],
            "size_bytes": attempt["size_bytes"],
            "audio_url": f"/recordings/{attempt['id']}",
        }

    def list_recordings(self, sentence_id: str) -> list[dict[str, Any]]:
        if sentence_id not in self.deck_ids:
            raise ValueError("Unknown sentence ID")
        with self.lock:
            attempts = [
                self.public_recording(attempt)
                for attempt in self.recordings["attempts"]
                if attempt["sentence_id"] == sentence_id
            ]
        return sorted(attempts, key=lambda item: item["created_at"], reverse=True)

    def save_recording(
        self,
        sentence_id: str,
        payload: bytes,
        content_type: str,
        duration_ms: int,
    ) -> dict[str, Any]:
        if sentence_id not in self.deck_ids:
            raise ValueError("Unknown sentence ID")
        mime_type, extension = normalize_recording_mime_type(content_type)
        if not 128 <= len(payload) <= MAX_RECORDING_BYTES:
            raise ValueError("Recording size is outside the allowed range")
        if not _is_nonnegative_integer(duration_ms) or duration_ms > MAX_RECORDING_DURATION_MS:
            raise ValueError("Recording duration is outside the allowed range")

        created_at = utc_timestamp()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        attempt_id = f"recording-{timestamp}-{secrets.token_hex(6)}"
        filename = f"{attempt_id}{extension}"
        self.recordings_directory.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            dir=self.recordings_directory,
            prefix=f".{attempt_id}.",
            suffix=".tmp",
            delete=False,
        )
        temporary_path = Path(handle.name)
        recording_path = self.recordings_directory / filename
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.replace(recording_path)
            attempt = {
                "id": attempt_id,
                "sentence_id": sentence_id,
                "created_at": created_at,
                "duration_ms": duration_ms,
                "mime_type": mime_type,
                "size_bytes": len(payload),
                "file": filename,
            }
            with self.lock:
                self.recordings["attempts"].append(attempt)
                try:
                    atomic_write_json(self.recordings_index_path, self.recordings)
                except Exception:
                    self.recordings["attempts"].pop()
                    raise
            return self.public_recording(attempt)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            recording_path.unlink(missing_ok=True)
            raise

    def recording_file(self, attempt_id: str) -> tuple[Path, str]:
        if not re.fullmatch(r"recording-[0-9TZ]{16}-[0-9a-f]{12}", attempt_id):
            raise ValueError("Invalid recording ID")
        with self.lock:
            attempt = next(
                (
                    item
                    for item in self.recordings["attempts"]
                    if item["id"] == attempt_id
                ),
                None,
            )
        if attempt is None:
            raise FileNotFoundError("Recording not found")
        return self.recordings_directory / attempt["file"], attempt["mime_type"]

    def delete_recording(self, attempt_id: str) -> bool:
        if not re.fullmatch(r"recording-[0-9TZ]{16}-[0-9a-f]{12}", attempt_id):
            raise ValueError("Invalid recording ID")
        with self.lock:
            index = next(
                (
                    position
                    for position, item in enumerate(self.recordings["attempts"])
                    if item["id"] == attempt_id
                ),
                None,
            )
            if index is None:
                return False
            attempt = self.recordings["attempts"].pop(index)
            try:
                atomic_write_json(self.recordings_index_path, self.recordings)
            except Exception:
                self.recordings["attempts"].insert(index, attempt)
                raise
        (self.recordings_directory / attempt["file"]).unlink(missing_ok=True)
        return True


def parse_range_header(value: str | None, size: int) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match:
        raise ValueError("Invalid byte range")
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise ValueError("Invalid byte range")
    if not start_text:
        suffix = int(end_text)
        if suffix <= 0:
            raise ValueError("Invalid byte range")
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    if start >= size or start > end:
        raise ValueError("Unsatisfiable byte range")
    return start, min(end, size - 1)


def handler_factory(application: DrillApplication) -> type[BaseHTTPRequestHandler]:
    class DrillRequestHandler(BaseHTTPRequestHandler):
        server_version = "ChineseDrill/0.1"

        def log_message(self, format_string: str, *args: Any) -> None:
            print(f"[{self.log_date_time_string()}] {format_string % args}")

        def send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def send_error_json(self, status: HTTPStatus, message: str) -> None:
            self.send_json({"error": message}, status)

        def serve_file(
            self,
            path: Path,
            *,
            immutable: bool = False,
            content_type: str | None = None,
        ) -> None:
            if not path.is_file():
                self.send_error_json(HTTPStatus.NOT_FOUND, "File not found")
                return
            size = path.stat().st_size
            try:
                byte_range = parse_range_header(self.headers.get("Range"), size)
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return

            response_content_type = (
                content_type
                or mimetypes.guess_type(path.name)[0]
                or "application/octet-stream"
            )
            if byte_range is None:
                start, end = 0, size - 1
                status = HTTPStatus.OK
            else:
                start, end = byte_range
                status = HTTPStatus.PARTIAL_CONTENT
            length = end - start + 1

            self.send_response(status)
            self.send_header("Content-Type", response_content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if byte_range is not None:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header(
                "Cache-Control",
                "public, max-age=31536000, immutable" if immutable else "no-cache",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command == "HEAD":
                return

            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/health":
                self.send_json(
                    {
                        "status": "ok",
                        "sentences": len(application.deck["sentences"]),
                    }
                )
                return
            if path == "/api/deck":
                self.send_json(application.deck)
                return
            if path == "/api/progress":
                with application.lock:
                    self.send_json(application.progress)
                return
            if path == "/api/recordings":
                sentence_ids = parse_qs(parsed.query).get("sentence_id", [])
                if len(sentence_ids) != 1:
                    self.send_error_json(
                        HTTPStatus.BAD_REQUEST, "One sentence_id is required"
                    )
                    return
                try:
                    attempts = application.list_recordings(sentence_ids[0])
                except ValueError as error:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                    return
                self.send_json({"attempts": attempts})
                return
            if path.startswith("/recordings/"):
                attempt_id = unquote(path.removeprefix("/recordings/"))
                try:
                    recording_path, mime_type = application.recording_file(attempt_id)
                except ValueError as error:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                    return
                except FileNotFoundError:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "Recording not found")
                    return
                self.serve_file(recording_path, content_type=mime_type)
                return
            if path.startswith("/audio/"):
                audio_url = f"/audio/{unquote(path[len('/audio/') :])}"
                try:
                    audio_path = resolve_audio_path(
                        audio_url, application.audio_directory
                    )
                except ValueError:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid audio path")
                    return
                self.serve_file(audio_path, immutable=True)
                return
            static_path = STATIC_FILES.get(path)
            if static_path is not None:
                self.serve_file(static_path)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

        def do_PUT(self) -> None:
            path = urlparse(self.path).path
            if path != "/api/progress":
                self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
                return
            content_length_text = self.headers.get("Content-Length")
            try:
                content_length = int(content_length_text or "")
            except ValueError:
                self.send_error_json(HTTPStatus.LENGTH_REQUIRED, "Content-Length required")
                return
            if content_length < 2 or content_length > MAX_PROGRESS_BYTES:
                self.send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Invalid body size")
                return
            try:
                payload = self.rfile.read(content_length)
                value = json.loads(payload.decode("utf-8"))
                saved = application.save_progress(value)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            self.send_json(saved)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/recordings":
                self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
                return
            sentence_ids = parse_qs(parsed.query).get("sentence_id", [])
            if len(sentence_ids) != 1:
                self.send_error_json(
                    HTTPStatus.BAD_REQUEST, "One sentence_id is required"
                )
                return
            try:
                content_length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self.send_error_json(
                    HTTPStatus.LENGTH_REQUIRED, "Content-Length required"
                )
                return
            if content_length < 128:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Recording is empty")
                return
            if content_length > MAX_RECORDING_BYTES:
                self.send_error_json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Recording is too large"
                )
                return
            try:
                duration_ms = int(
                    self.headers.get("X-Recording-Duration-Ms") or ""
                )
                payload = self.rfile.read(content_length)
                attempt = application.save_recording(
                    sentence_ids[0],
                    payload,
                    self.headers.get("Content-Type") or "",
                    duration_ms,
                )
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            self.send_json(attempt, HTTPStatus.CREATED)

        def do_DELETE(self) -> None:
            path = urlparse(self.path).path
            if not path.startswith("/api/recordings/"):
                self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
                return
            attempt_id = unquote(path.removeprefix("/api/recordings/"))
            try:
                deleted = application.delete_recording(attempt_id)
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            if not deleted:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Recording not found")
                return
            self.send_json({"deleted": True, "id": attempt_id})

    return DrillRequestHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Chinese drill app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validate data and exit")
    parser.add_argument("--deck", type=Path, default=DECK_PATH)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument("--audio-directory", type=Path, default=AUDIO_DIRECTORY)
    parser.add_argument(
        "--recordings-directory",
        type=Path,
        help="Recording storage (defaults to a recordings folder beside progress.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    deck_path = args.deck.expanduser().resolve()
    progress_path = args.progress.expanduser().resolve()
    audio_directory = args.audio_directory.expanduser().resolve()
    recordings_directory = (
        args.recordings_directory.expanduser().resolve()
        if args.recordings_directory
        else progress_path.parent / "recordings"
    )
    application = DrillApplication(
        deck_path, progress_path, audio_directory, recordings_directory
    )
    sentence_count = len(application.deck["sentences"])
    if args.check:
        print(f"App data is valid: {sentence_count} sentences and audio files.")
        print(f"Progress file: {progress_path}")
        print(f"Recordings directory: {recordings_directory}")
        return 0

    server = ThreadingHTTPServer(
        (args.host, args.port), handler_factory(application), bind_and_activate=False
    )
    server.allow_reuse_address = True
    try:
        server.server_bind()
        server.server_activate()
    except OSError as error:
        server.server_close()
        raise RuntimeError(
            f"Could not start on http://{args.host}:{args.port}: {error}"
        ) from error

    url = f"http://{args.host}:{server.server_port}"
    print(f"Chinese Drill is ready: {url}")
    print(f"Loaded {sentence_count} sentences. Press Ctrl-C to stop.")
    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping Chinese Drill.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=os.sys.stderr)
        raise SystemExit(1)
