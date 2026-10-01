#!/usr/bin/env python3
"""Combine the sentence deck and audio manifest into app-ready JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from common import (
    AUDIO_DIR,
    BUILD_DIR,
    DIST_DIR,
    PROJECT_ROOT,
    atomic_write_json,
    read_json,
    require_string,
    utc_timestamp,
)


DEFAULT_DECK = BUILD_DIR / "sentences.json"
DEFAULT_MANIFEST = BUILD_DIR / "audio-manifest.json"
DEFAULT_OUTPUT = DIST_DIR / "deck.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the validated JSON bundle consumed by the future app."
    )
    parser.add_argument("--deck", type=Path, default=DEFAULT_DECK)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audio-directory", type=Path, default=AUDIO_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-missing-audio",
        action="store_true",
        help="Build entries with null audio paths instead of failing",
    )
    return parser.parse_args()


def build_bundle(
    deck: dict[str, Any],
    manifest: dict[str, Any],
    audio_directory: Path,
    allow_missing_audio: bool,
) -> dict[str, Any]:
    sentences = deck.get("sentences")
    items = manifest.get("items")
    if not isinstance(sentences, list) or not sentences:
        raise ValueError("The compiled sentence deck is empty")
    if not isinstance(items, dict):
        raise ValueError("The audio manifest has no items object")

    app_sentences: list[dict[str, Any]] = []
    missing: list[str] = []
    for sentence in sentences:
        if not isinstance(sentence, dict):
            raise ValueError("Every sentence must be an object")
        sentence_id = require_string(sentence.get("id"), "sentence.id")
        audio_entry = items.get(sentence_id)
        audio_url: str | None = None
        if isinstance(audio_entry, dict):
            filename = audio_entry.get("audio_file")
            if isinstance(filename, str) and filename:
                audio_path = audio_directory / filename
                if audio_path.is_file() and audio_path.stat().st_size >= 100:
                    audio_url = f"/audio/{filename}"

        if audio_url is None:
            missing.append(sentence_id)

        app_sentences.append(
            {
                "id": sentence_id,
                "chinese": require_string(
                    sentence.get("chinese"), f"{sentence_id}.chinese"
                ),
                "pinyin": require_string(
                    sentence.get("pinyin"), f"{sentence_id}.pinyin"
                ),
                "english_hint": require_string(
                    sentence.get("english_hint"), f"{sentence_id}.english_hint"
                ),
                "scenario": require_string(
                    sentence.get("scenario"), f"{sentence_id}.scenario"
                ),
                "focus": sentence.get("focus", []),
                "priority": sentence.get("priority"),
                "default_repetitions": sentence.get("default_repetitions", 3),
                "audio": audio_url,
                "sources": sentence.get("sources", []),
            }
        )

    if missing and not allow_missing_audio:
        preview = ", ".join(missing[:8])
        suffix = "" if len(missing) <= 8 else f" and {len(missing) - 8} more"
        raise ValueError(
            f"Missing audio for {len(missing)} sentence(s): {preview}{suffix}. "
            "Run synthesize_audio.py first or pass --allow-missing-audio."
        )

    return {
        "version": 1,
        "built_at": utc_timestamp(),
        "sentence_count": len(app_sentences),
        "missing_audio_count": len(missing),
        "sentences": app_sentences,
    }


def main() -> int:
    args = parse_args()
    deck_path = args.deck.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    audio_directory = args.audio_directory.expanduser().resolve()
    output = args.output.expanduser().resolve()

    deck = read_json(deck_path)
    if manifest_path.exists():
        manifest = read_json(manifest_path)
    elif args.allow_missing_audio:
        manifest = {"version": 1, "items": {}}
    else:
        raise FileNotFoundError(f"Audio manifest not found: {manifest_path}")
    if not isinstance(deck, dict) or not isinstance(manifest, dict):
        raise ValueError("Deck and manifest must both be JSON objects")

    bundle = build_bundle(
        deck, manifest, audio_directory, args.allow_missing_audio
    )
    atomic_write_json(output, bundle)
    print(
        f"Built {bundle['sentence_count']} app entries "
        f"({bundle['missing_audio_count']} missing audio)."
    )
    try:
        print(f"Output: {output.relative_to(PROJECT_ROOT)}")
    except ValueError:
        print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)

