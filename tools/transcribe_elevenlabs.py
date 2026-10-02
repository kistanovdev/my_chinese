#!/usr/bin/env python3
"""Transcribe lesson videos with ElevenLabs Speech to Text.

By default, this scans ``Berlitz 5/records and analysis`` for files named
``YYYY-MM-DD-01-video.mp4`` and creates the corresponding
``YYYY-MM-DD-02-transcription.txt`` only when it does not already exist.

Examples:
    python3 tools/transcribe_elevenlabs.py --dry-run
    python3 tools/transcribe_elevenlabs.py
    python3 tools/transcribe_elevenlabs.py path/to/video.mp4

Put the API key in ``.env`` at the project root:
    ELEVENLABS_API_KEY=your_api_key

On macOS the script uses verified system ``curl`` by default, so it does not
require third-party Python packages and honors certificates trusted by
Keychain.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


API_URL = "https://api.elevenlabs.io/v1/speech-to-text"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "Berlitz 5" / "records and analysis"
VIDEO_SUFFIX = "-01-video.mp4"
TRANSCRIPT_SUFFIX = "-02-transcription.txt"


def load_dotenv_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without replacing exported variables."""
    if not path.is_file():
        return

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid .env entry on line {line_number}")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not key.replace("_", "a").isalnum() or key[0].isdigit():
            raise ValueError(f"Invalid .env key on line {line_number}")

        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()

        os.environ.setdefault(key, value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Transcribe MP4 lesson videos that do not yet have matching "
            "transcription files."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help="A video or directory (default: Berlitz 5/records and analysis)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List work without uploading videos or writing transcripts",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace transcription files that already exist",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search subdirectories when the input is a directory",
    )
    parser.add_argument(
        "--model",
        default="scribe_v2",
        help="ElevenLabs model ID (default: scribe_v2)",
    )
    parser.add_argument(
        "--language",
        default="zho",
        help="ISO language code, or 'auto' for detection (default: zho)",
    )
    parser.add_argument(
        "--num-speakers",
        type=int,
        default=2,
        help="Expected maximum speaker count; use 0 for automatic (default: 2)",
    )
    parser.add_argument(
        "--no-diarize",
        action="store_true",
        help="Disable speaker identification",
    )
    parser.add_argument(
        "--no-audio-events",
        action="store_true",
        help="Do not include events such as laughter or applause",
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        help="Also save the complete API response beside each transcript",
    )
    parser.add_argument(
        "--compress-audio",
        action="store_true",
        help=(
            "Extract temporary mono speech audio with ffmpeg before upload; "
            "the source video is never modified"
        ),
    )
    parser.add_argument(
        "--transport",
        choices=("auto", "curl", "requests"),
        default="auto",
        help="HTTPS transport (default: verified system curl on macOS)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=7200,
        help="Per-upload response timeout in seconds (default: 7200)",
    )
    parser.add_argument(
        "--api-key-env",
        default="ELEVENLABS_API_KEY",
        help=(
            "API-key variable loaded from the project-root .env file "
            "(default: ELEVENLABS_API_KEY)"
        ),
    )
    return parser.parse_args()


def transcript_path(video: Path) -> Path:
    if not video.name.endswith(VIDEO_SUFFIX):
        raise ValueError(
            f"Video name must end with {VIDEO_SUFFIX!r}: {video.name}"
        )
    base = video.name[: -len(VIDEO_SUFFIX)]
    return video.with_name(base + TRANSCRIPT_SUFFIX)


def find_videos(input_path: Path, recursive: bool) -> list[Path]:
    input_path = input_path.expanduser().resolve()
    if input_path.is_file():
        if input_path.suffix.lower() != ".mp4":
            raise ValueError(f"Input file is not an MP4: {input_path}")
        transcript_path(input_path)
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input does not exist: {input_path}")

    iterator = input_path.rglob(f"*{VIDEO_SUFFIX}") if recursive else input_path.glob(
        f"*{VIDEO_SUFFIX}"
    )
    return sorted(path.resolve() for path in iterator if path.is_file())


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def speaker_label(speaker_id: str | None) -> str:
    if not speaker_id:
        return "Speaker"
    normalized = speaker_id.replace("speaker_", "Speaker ").replace("_", " ")
    return normalized[:1].upper() + normalized[1:]


def format_transcript(response_data: dict[str, Any]) -> str:
    """Render word-level API output in the repository's timestamped format."""
    words = response_data.get("words") or []
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for item in words:
        text = str(item.get("text") or "")
        start = item.get("start")
        end = item.get("end")
        if not text or start is None or end is None:
            continue

        start = float(start)
        end = float(end)
        speaker = item.get("speaker_id")
        if speaker is None and current is not None:
            speaker = current["speaker"]
        speaker = str(speaker) if speaker is not None else None

        should_split = current is not None and (
            speaker != current["speaker"]
            or start - current["end"] > 1.25
            or end - current["start"] > 20.0
        )
        if should_split:
            segments.append(current)
            current = None

        if current is None:
            current = {
                "start": start,
                "end": end,
                "speaker": speaker,
                "parts": [text],
            }
        else:
            current["end"] = end
            current["parts"].append(text)

    if current is not None:
        segments.append(current)

    if not segments:
        plain_text = str(response_data.get("text") or "").strip()
        if not plain_text:
            raise ValueError("ElevenLabs returned no transcript text")
        return plain_text + "\n"

    blocks = []
    for segment in segments:
        text = "".join(segment["parts"]).strip()
        if not text:
            continue
        blocks.append(
            f"{format_timestamp(segment['start'])} --> "
            f"{format_timestamp(segment['end'])} "
            f"[{speaker_label(segment['speaker'])}]\n{text}"
        )
    return "\n\n".join(blocks) + "\n"


def transcribe_with_requests(
    media: Path,
    *,
    api_key: str,
    model: str,
    language: str,
    num_speakers: int,
    diarize: bool,
    tag_audio_events: bool,
    timeout: float,
) -> dict[str, Any]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "The 'requests' package is required. Install it with: "
            "python3 -m pip install requests"
        ) from exc

    fields: dict[str, str] = {
        "model_id": model,
        "diarize": str(diarize).lower(),
        "tag_audio_events": str(tag_audio_events).lower(),
        "timestamps_granularity": "word",
    }
    if language.lower() != "auto":
        fields["language_code"] = language
    if num_speakers > 0:
        fields["num_speakers"] = str(num_speakers)

    mime_type = "audio/mpeg" if media.suffix.lower() == ".mp3" else "video/mp4"
    with media.open("rb") as media_file:
        response = requests.post(
            API_URL,
            headers={"xi-api-key": api_key},
            data=fields,
            files={"file": (media.name, media_file, mime_type)},
            timeout=(30, timeout),
        )

    if not response.ok:
        detail = response.text[:2000]
        raise RuntimeError(
            f"ElevenLabs returned HTTP {response.status_code}: {detail}"
        )
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("ElevenLabs returned an unexpected response shape")
    return result


def transcribe_with_curl(
    media: Path,
    *,
    api_key: str,
    model: str,
    language: str,
    num_speakers: int,
    diarize: bool,
    tag_audio_events: bool,
    timeout: float,
) -> dict[str, Any]:
    curl = shutil.which("curl")
    if curl is None:
        raise RuntimeError("System curl is not installed")
    mime_type = "audio/mpeg" if media.suffix.lower() == ".mp3" else "video/mp4"

    with tempfile.TemporaryDirectory(prefix="berlitz-scribe-request-") as temp_name:
        temp_directory = Path(temp_name)
        headers_path = temp_directory / "headers.txt"
        response_path = temp_directory / "response.json"
        headers_path.write_text(
            f"xi-api-key: {api_key}\nAccept: application/json\n",
            encoding="utf-8",
        )
        headers_path.chmod(0o600)
        command = [
            curl,
            "--silent",
            "--show-error",
            "--request",
            "POST",
            "--connect-timeout",
            "30",
            "--max-time",
            str(timeout),
            "--header",
            f"@{headers_path}",
            "--form",
            f"file=@{media};type={mime_type}",
            "--form-string",
            f"model_id={model}",
            "--form-string",
            f"diarize={str(diarize).lower()}",
            "--form-string",
            f"tag_audio_events={str(tag_audio_events).lower()}",
            "--form-string",
            "timestamps_granularity=word",
            "--output",
            str(response_path),
            "--write-out",
            "%{http_code}",
        ]
        if language.lower() != "auto":
            command.extend(["--form-string", f"language_code={language}"])
        if num_speakers > 0:
            command.extend(["--form-string", f"num_speakers={num_speakers}"])
        command.append(API_URL)

        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or f"curl exit code {result.returncode}"
            raise RuntimeError(f"ElevenLabs request failed: {detail}")
        try:
            status = int(result.stdout.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"curl returned an invalid HTTP status: {result.stdout!r}"
            ) from exc
        response_text = (
            response_path.read_text(encoding="utf-8", errors="replace")
            if response_path.exists()
            else ""
        )
        if status < 200 or status >= 300:
            raise RuntimeError(
                f"ElevenLabs returned HTTP {status}: {response_text[:2000]}"
            )
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ElevenLabs returned invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("ElevenLabs returned an unexpected response shape")
        return parsed


def resolve_transport(requested: str) -> str:
    if requested != "auto":
        return requested
    if sys.platform == "darwin" and shutil.which("curl"):
        return "curl"
    return "requests"


def compress_speech_audio(video: Path, output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for --compress-audio")
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(output),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 100:
        detail = result.stderr.strip()[-2000:]
        raise RuntimeError(f"ffmpeg audio extraction failed: {detail}")


def write_text_atomically(path: Path, text: str) -> None:
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(text, encoding="utf-8")
    temporary_path.replace(path)


def main() -> int:
    args = parse_args()
    try:
        load_dotenv_file(PROJECT_ROOT / ".env")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: could not load {PROJECT_ROOT / '.env'}: {exc}", file=sys.stderr)
        return 2

    try:
        videos = find_videos(args.input, args.recursive)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    pending: list[tuple[Path, Path]] = []
    for video in videos:
        output = transcript_path(video)
        output_is_complete = output.is_file() and output.stat().st_size >= 100
        if output_is_complete and not args.force:
            print(f"skip: {video.name} (already has {output.name})")
        else:
            pending.append((video, output))
            reason = " (replacing incomplete file)" if output.exists() else ""
            print(f"pending: {video.name} -> {output.name}{reason}")

    if not videos:
        print("No matching videos found.")
        return 0
    if not pending:
        print("Nothing to transcribe.")
        return 0
    if args.dry_run:
        print(f"Dry run: {len(pending)} video(s) would be uploaded.")
        return 0

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(
            f"error: set {args.api_key_env} in {PROJECT_ROOT / '.env'} "
            "or export it in the shell",
            file=sys.stderr,
        )
        return 2

    transport = resolve_transport(args.transport)
    if transport == "curl" and shutil.which("curl") is None:
        print("error: curl transport selected but curl is unavailable", file=sys.stderr)
        return 2
    if args.compress_audio and shutil.which("ffmpeg") is None:
        print("error: --compress-audio requires ffmpeg", file=sys.stderr)
        return 2
    transcriber = (
        transcribe_with_curl if transport == "curl" else transcribe_with_requests
    )
    print(f"HTTPS transport: {transport}")

    failures = 0
    for index, (video, output) in enumerate(pending, start=1):
        print(f"[{index}/{len(pending)}] Preparing {video.name} ...", flush=True)
        try:
            with tempfile.TemporaryDirectory(
                prefix="berlitz-scribe-audio-"
            ) as temp_name:
                media = video
                if args.compress_audio:
                    media = Path(temp_name) / f"{video.stem}.mp3"
                    compress_speech_audio(video, media)
                    print(
                        f"        compressed upload: {media.stat().st_size / 1024 / 1024:.1f} MiB",
                        flush=True,
                    )
                print(f"        uploading with ElevenLabs Scribe ...", flush=True)
                result = transcriber(
                    media,
                    api_key=api_key,
                    model=args.model,
                    language=args.language,
                    num_speakers=args.num_speakers,
                    diarize=not args.no_diarize,
                    tag_audio_events=not args.no_audio_events,
                    timeout=args.timeout,
                )
            write_text_atomically(output, format_transcript(result))
            if args.save_json:
                json_path = output.with_suffix(".json")
                write_text_atomically(
                    json_path,
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                )
            print(f"saved: {output}")
        except Exception as exc:  # Continue so a later rerun can resume the batch.
            failures += 1
            print(f"failed: {video.name}: {exc}", file=sys.stderr)

    succeeded = len(pending) - failures
    print(f"Finished: {succeeded} succeeded, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
