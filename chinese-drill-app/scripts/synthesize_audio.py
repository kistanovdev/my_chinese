#!/usr/bin/env python3
"""Generate and cache ElevenLabs audio for a compiled sentence deck."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from common import (
    AUDIO_DIR,
    BUILD_DIR,
    PROJECT_ROOT,
    atomic_write_json,
    load_dotenv,
    read_json,
    require_string,
    utc_timestamp,
)


API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_DECK = BUILD_DIR / "sentences.json"
DEFAULT_MANIFEST = BUILD_DIR / "audio-manifest.json"


class ElevenLabsHTTPError(RuntimeError):
    """An ElevenLabs response with a retry-relevant HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate missing ElevenLabs MP3 files for the compiled deck."
    )
    parser.add_argument("--deck", type=Path, default=DEFAULT_DECK)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audio-directory", type=Path, default=AUDIO_DIR)
    parser.add_argument(
        "--limit",
        type=int,
        help="Generate at most this many files (useful for voice previews)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Regenerate audio even when cached"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and list work without API calls",
    )
    parser.add_argument(
        "--timeout", type=float, default=180, help="Request timeout in seconds"
    )
    parser.add_argument(
        "--max-attempts", type=int, default=4, help="Attempts for transient failures"
    )
    parser.add_argument(
        "--transport",
        choices=("auto", "urllib", "curl"),
        default=os.environ.get("ELEVENLABS_HTTP_TRANSPORT", "auto"),
        help=(
            "HTTPS transport (default: auto; uses verified system curl on macOS "
            "and Python urllib elsewhere)"
        ),
    )
    return parser.parse_args()


def audio_hash(
    text: str, model_id: str, voice_id: str, output_format: str, language_code: str
) -> str:
    serialized = json.dumps(
        {
            "text": text,
            "model_id": model_id,
            "voice_id": voice_id,
            "output_format": output_format,
            "language_code": language_code,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def api_error_message(error: HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    body = body.strip()
    if len(body) > 1000:
        body = body[:1000] + "..."
    return f"HTTP {error.code}: {body or error.reason}"


def request_details(
    voice_id: str,
    output_format: str,
    text: str,
    model_id: str,
    language_code: str,
) -> tuple[str, bytes]:
    query = urlencode({"output_format": output_format})
    url = f"{API_BASE}/{quote(voice_id, safe='')}?{query}"
    payload: dict[str, Any] = {"text": text, "model_id": model_id}
    if language_code:
        payload["language_code"] = language_code
    return url, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def generate_audio_with_urllib(
    *,
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    language_code: str,
    text: str,
    timeout: float,
) -> tuple[bytes, str | None]:
    url, body = request_details(
        voice_id, output_format, text, model_id, language_code
    )
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "User-Agent": "chinese-drill-app/0.1",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        audio = response.read()
        request_id = response.headers.get("request-id") or response.headers.get(
            "x-request-id"
        )
        if len(audio) < 100:
            raise RuntimeError("ElevenLabs returned an unexpectedly small file")
        return audio, request_id


def response_request_id(header_text: str) -> str | None:
    for line in header_text.splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip().lower() in {"request-id", "x-request-id"}:
            return value.strip() or None
    return None


def generate_audio_with_curl(
    *,
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    language_code: str,
    text: str,
    timeout: float,
) -> tuple[bytes, str | None]:
    curl = shutil.which("curl")
    if curl is None:
        raise RuntimeError("System curl is not installed")
    url, body = request_details(
        voice_id, output_format, text, model_id, language_code
    )

    # Sensitive headers live only in a private temporary directory. The API key
    # is never placed in argv, stdout, or stderr.
    with tempfile.TemporaryDirectory(prefix="chinese-drill-elevenlabs-") as temp_name:
        temp_directory = Path(temp_name)
        headers_path = temp_directory / "request-headers.txt"
        payload_path = temp_directory / "request.json"
        response_headers_path = temp_directory / "response-headers.txt"
        response_path = temp_directory / "response.bin"
        headers_path.write_text(
            "\n".join(
                [
                    f"xi-api-key: {api_key}",
                    "Content-Type: application/json",
                    "Accept: audio/mpeg",
                    "User-Agent: chinese-drill-app/0.1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        payload_path.write_bytes(body)
        headers_path.chmod(0o600)
        payload_path.chmod(0o600)

        result = subprocess.run(
            [
                curl,
                "--silent",
                "--show-error",
                "--request",
                "POST",
                "--connect-timeout",
                str(min(timeout, 30)),
                "--max-time",
                str(timeout),
                "--header",
                f"@{headers_path}",
                "--data-binary",
                f"@{payload_path}",
                "--output",
                str(response_path),
                "--dump-header",
                str(response_headers_path),
                "--write-out",
                "%{http_code}",
                url,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            details = result.stderr.strip() or f"curl exit code {result.returncode}"
            raise URLError(details)

        try:
            status = int(result.stdout.strip())
        except ValueError as error:
            raise RuntimeError(
                f"curl returned an invalid HTTP status: {result.stdout!r}"
            ) from error
        response = response_path.read_bytes() if response_path.exists() else b""
        header_text = (
            response_headers_path.read_text(encoding="utf-8", errors="replace")
            if response_headers_path.exists()
            else ""
        )
        if status < 200 or status >= 300:
            message = response.decode("utf-8", errors="replace").strip()
            if len(message) > 1000:
                message = message[:1000] + "..."
            raise ElevenLabsHTTPError(
                status, f"HTTP {status}: {message or 'ElevenLabs request failed'}"
            )
        if len(response) < 100:
            raise RuntimeError("ElevenLabs returned an unexpectedly small file")
        return response, response_request_id(header_text)


def resolve_transport(requested: str) -> str:
    if requested != "auto":
        return requested
    if sys.platform == "darwin" and shutil.which("curl"):
        return "curl"
    return "urllib"


def generate_audio(
    *,
    transport: str,
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    language_code: str,
    text: str,
    timeout: float,
    max_attempts: int,
) -> tuple[bytes, str | None]:
    generator = (
        generate_audio_with_curl
        if transport == "curl"
        else generate_audio_with_urllib
    )

    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        try:
            return generator(
                api_key=api_key,
                voice_id=voice_id,
                model_id=model_id,
                output_format=output_format,
                language_code=language_code,
                text=text,
                timeout=timeout,
            )
        except HTTPError as error:
            last_error = api_error_message(error)
            retryable = error.code == 429 or 500 <= error.code <= 599
            if not retryable or attempt == max_attempts:
                break
        except ElevenLabsHTTPError as error:
            last_error = str(error)
            retryable = error.status == 429 or 500 <= error.status <= 599
            if not retryable or attempt == max_attempts:
                break
        except (URLError, TimeoutError, RuntimeError) as error:
            last_error = str(error)
            if attempt == max_attempts:
                break

        delay = min(2 ** (attempt - 1), 30)
        print(f"             transient error; retrying in {delay}s", flush=True)
        time.sleep(delay)

    raise RuntimeError(f"ElevenLabs generation failed after {max_attempts} attempts: {last_error}")


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "items": {}}
    value = read_json(path)
    if not isinstance(value, dict) or not isinstance(value.get("items"), dict):
        raise ValueError(f"Invalid audio manifest: {path}")
    return value


def main() -> int:
    args = parse_args()
    load_dotenv()

    model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_v4").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    output_format = os.environ.get(
        "ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128"
    ).strip()
    language_code = os.environ.get("ELEVENLABS_LANGUAGE_CODE", "zh").strip()
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    transport = resolve_transport(args.transport)

    if not voice_id:
        raise ValueError("Set ELEVENLABS_VOICE_ID in .env before generating audio")
    if not args.dry_run and not api_key:
        raise ValueError("Set ELEVENLABS_API_KEY in .env before generating audio")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be at least 1")
    if args.max_attempts < 1:
        raise ValueError("--max-attempts must be at least 1")
    if transport == "curl" and shutil.which("curl") is None:
        raise ValueError("curl transport selected, but system curl is unavailable")

    deck_path = args.deck.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    audio_directory = args.audio_directory.expanduser().resolve()
    deck = read_json(deck_path)
    sentences = deck.get("sentences") if isinstance(deck, dict) else None
    if not isinstance(sentences, list) or not sentences:
        raise ValueError(f"Compiled deck has no sentences: {deck_path}")

    manifest = load_manifest(manifest_path)
    items: dict[str, Any] = manifest["items"]
    audio_directory.mkdir(parents=True, exist_ok=True)
    print(f"HTTPS transport: {transport}")

    generated = 0
    skipped = 0
    considered = 0
    for sentence in sentences:
        sentence_id = require_string(sentence.get("id"), "sentence.id")
        text = require_string(sentence.get("tts_text"), f"{sentence_id}.tts_text")
        digest = audio_hash(
            text, model_id, voice_id, output_format, language_code
        )
        filename = f"{sentence_id}-{digest}.mp3"
        audio_path = audio_directory / filename
        cached = items.get(sentence_id)
        cache_matches = (
            isinstance(cached, dict)
            and cached.get("content_hash") == digest
            and cached.get("audio_file") == filename
            and audio_path.is_file()
            and audio_path.stat().st_size >= 100
        )
        if cache_matches and not args.force:
            skipped += 1
            continue
        if args.limit is not None and considered >= args.limit:
            continue
        considered += 1

        if args.dry_run:
            print(f"would generate {sentence_id}: {text} -> audio/{filename}")
            generated += 1
            continue

        print(f"generating {sentence_id}: {text}", flush=True)
        audio, request_id = generate_audio(
            transport=transport,
            api_key=api_key,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
            language_code=language_code,
            text=text,
            timeout=args.timeout,
            max_attempts=args.max_attempts,
        )
        temporary_path = audio_path.with_suffix(audio_path.suffix + ".tmp")
        temporary_path.write_bytes(audio)
        temporary_path.replace(audio_path)
        items[sentence_id] = {
            "audio_file": filename,
            "content_hash": digest,
            "text": text,
            "model_id": model_id,
            "voice_id": voice_id,
            "output_format": output_format,
            "language_code": language_code,
            "generated_at": utc_timestamp(),
            "request_id": request_id,
        }
        manifest.update(
            {
                "version": 1,
                "updated_at": utc_timestamp(),
                "items": items,
            }
        )
        atomic_write_json(manifest_path, manifest)
        generated += 1

    if args.dry_run:
        print(f"Dry run: {generated} would generate, {skipped} cached.")
    else:
        print(f"Done: {generated} generated, {skipped} cached.")
        try:
            print(f"Manifest: {manifest_path.relative_to(PROJECT_ROOT)}")
        except ValueError:
            print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
