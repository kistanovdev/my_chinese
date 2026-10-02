#!/usr/bin/env python3
"""Generate additional speaker variants without replacing primary audio."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from common import (
    AUDIO_DIR,
    BUILD_DIR,
    DATA_DIR,
    PROJECT_ROOT,
    atomic_write_json,
    load_dotenv,
    read_json,
    require_string,
    utc_timestamp,
)
from synthesize_audio import audio_hash, generate_audio, resolve_transport


DEFAULT_DECK = BUILD_DIR / "sentences.json"
DEFAULT_VOICES = DATA_DIR / "voices.json"
DEFAULT_MANIFEST = BUILD_DIR / "audio-variants-manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate cached audio for the additional configured speakers."
    )
    parser.add_argument("--deck", type=Path, default=DEFAULT_DECK)
    parser.add_argument("--voices", type=Path, default=DEFAULT_VOICES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audio-directory", type=Path, default=AUDIO_DIR)
    parser.add_argument(
        "--voice",
        action="append",
        default=[],
        help="Only generate this voice key; repeat to select multiple voices",
    )
    parser.add_argument(
        "--limit", type=int, help="Generate at most this many audio files"
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument(
        "--transport",
        choices=("auto", "urllib", "curl"),
        default=os.environ.get("ELEVENLABS_HTTP_TRANSPORT", "auto"),
    )
    return parser.parse_args()


def load_voice_catalog(path: Path) -> list[dict[str, Any]]:
    value = read_json(path)
    voices = value.get("voices") if isinstance(value, dict) else None
    if not isinstance(voices, list) or not voices:
        raise ValueError(f"Voice catalog has no voices: {path}")

    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    primary_count = 0
    for index, voice in enumerate(voices, start=1):
        if not isinstance(voice, dict):
            raise ValueError(f"Voice {index} must be an object")
        key = require_string(voice.get("key"), f"voice {index}.key")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key):
            raise ValueError(f"Voice key is not URL-safe: {key}")
        if key in keys:
            raise ValueError(f"Duplicate voice key: {key}")
        keys.add(key)
        normalized = {
            "key": key,
            "name": require_string(voice.get("name"), f"{key}.name"),
            "voice_id": require_string(voice.get("voice_id"), f"{key}.voice_id"),
            "gender": require_string(voice.get("gender"), f"{key}.gender"),
            "accent": require_string(voice.get("accent"), f"{key}.accent"),
            "primary": voice.get("primary") is True,
        }
        primary_count += int(normalized["primary"])
        result.append(normalized)
    if primary_count != 1:
        raise ValueError("Voice catalog must contain exactly one primary voice")
    return result


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "voices": [], "items": {}}
    value = read_json(path)
    if not isinstance(value, dict) or not isinstance(value.get("items"), dict):
        raise ValueError(f"Invalid voice variants manifest: {path}")
    return value


def main() -> int:
    args = parse_args()
    load_dotenv()
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_v4").strip()
    output_format = os.environ.get(
        "ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128"
    ).strip()
    language_code = os.environ.get("ELEVENLABS_LANGUAGE_CODE", "zh").strip()
    transport = resolve_transport(args.transport)

    if not args.dry_run and not api_key:
        raise ValueError("Set ELEVENLABS_API_KEY in .env before generating audio")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be at least 1")
    if args.max_attempts < 1:
        raise ValueError("--max-attempts must be at least 1")
    if transport == "curl" and shutil.which("curl") is None:
        raise ValueError("curl transport selected, but system curl is unavailable")

    deck_path = args.deck.expanduser().resolve()
    voices_path = args.voices.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    audio_directory = args.audio_directory.expanduser().resolve()
    deck = read_json(deck_path)
    sentences = deck.get("sentences") if isinstance(deck, dict) else None
    if not isinstance(sentences, list) or not sentences:
        raise ValueError(f"Compiled deck has no sentences: {deck_path}")

    all_voices = load_voice_catalog(voices_path)
    requested = set(args.voice)
    unknown = requested - {voice["key"] for voice in all_voices}
    if unknown:
        raise ValueError(f"Unknown voice key(s): {', '.join(sorted(unknown))}")
    voices = [
        voice
        for voice in all_voices
        if not voice["primary"] and (not requested or voice["key"] in requested)
    ]
    if not voices:
        raise ValueError("No additional voices selected")

    manifest = load_manifest(manifest_path)
    items: dict[str, Any] = manifest["items"]
    audio_directory.mkdir(parents=True, exist_ok=True)
    print(f"HTTPS transport: {transport}")
    print(f"Additional speakers: {', '.join(voice['name'] for voice in voices)}")

    generated = 0
    skipped = 0
    total_characters = 0
    for sentence in sentences:
        sentence_id = require_string(sentence.get("id"), "sentence.id")
        text = require_string(sentence.get("tts_text"), f"{sentence_id}.tts_text")
        sentence_items = items.setdefault(sentence_id, {})
        if not isinstance(sentence_items, dict):
            raise ValueError(f"Invalid manifest entry for {sentence_id}")

        for voice in voices:
            digest = audio_hash(
                text,
                model_id,
                voice["voice_id"],
                output_format,
                language_code,
            )
            filename = f"{sentence_id}-{voice['key']}-{digest}.mp3"
            audio_path = audio_directory / filename
            cached = sentence_items.get(voice["key"])
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
            if args.limit is not None and generated >= args.limit:
                continue

            if args.dry_run:
                print(
                    f"would generate {sentence_id} with {voice['name']}: "
                    f"{text} -> audio/{filename}"
                )
                generated += 1
                total_characters += len(text)
                continue

            print(
                f"generating {sentence_id} with {voice['name']}: {text}",
                flush=True,
            )
            audio, request_id = generate_audio(
                transport=transport,
                api_key=api_key,
                voice_id=voice["voice_id"],
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
            sentence_items[voice["key"]] = {
                "audio_file": filename,
                "content_hash": digest,
                "text": text,
                "model_id": model_id,
                "voice_id": voice["voice_id"],
                "output_format": output_format,
                "language_code": language_code,
                "generated_at": utc_timestamp(),
                "request_id": request_id,
            }
            manifest.update(
                {
                    "version": 1,
                    "updated_at": utc_timestamp(),
                    "voices": all_voices,
                    "items": items,
                }
            )
            atomic_write_json(manifest_path, manifest)
            generated += 1
            total_characters += len(text)

    action = "would generate" if args.dry_run else "generated"
    print(
        f"Done: {generated} {action}, {skipped} cached "
        f"({total_characters:,} input characters this run)."
    )
    if not args.dry_run:
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
