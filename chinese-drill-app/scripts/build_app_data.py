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
    DATA_DIR,
    DIST_DIR,
    PROJECT_ROOT,
    atomic_write_json,
    read_json,
    require_string,
    utc_timestamp,
)


DEFAULT_DECK = BUILD_DIR / "sentences.json"
DEFAULT_MANIFEST = BUILD_DIR / "audio-manifest.json"
DEFAULT_VARIANTS_MANIFEST = BUILD_DIR / "audio-variants-manifest.json"
DEFAULT_VOICES = DATA_DIR / "voices.json"
DEFAULT_OUTPUT = DIST_DIR / "deck.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the validated JSON bundle consumed by the future app."
    )
    parser.add_argument("--deck", type=Path, default=DEFAULT_DECK)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--variants-manifest", type=Path, default=DEFAULT_VARIANTS_MANIFEST
    )
    parser.add_argument("--voices", type=Path, default=DEFAULT_VOICES)
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
    variants_manifest: dict[str, Any] | None = None,
    voice_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sentences = deck.get("sentences")
    items = manifest.get("items")
    if not isinstance(sentences, list) or not sentences:
        raise ValueError("The compiled sentence deck is empty")
    if not isinstance(items, dict):
        raise ValueError("The audio manifest has no items object")

    voices = voice_catalog.get("voices", []) if isinstance(voice_catalog, dict) else []
    voice_by_id = {
        voice.get("voice_id"): voice
        for voice in voices
        if isinstance(voice, dict) and isinstance(voice.get("voice_id"), str)
    }
    primary_voice = next(
        (voice for voice in voices if isinstance(voice, dict) and voice.get("primary") is True),
        None,
    )
    variant_items = (
        variants_manifest.get("items", {})
        if isinstance(variants_manifest, dict)
        else {}
    )
    if not isinstance(variant_items, dict):
        raise ValueError("The voice variants manifest has no items object")

    app_sentences: list[dict[str, Any]] = []
    missing: list[str] = []
    variant_audio_count = 0
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

        audio_variants: list[dict[str, Any]] = []
        if audio_url is not None:
            base_voice = None
            if isinstance(audio_entry, dict):
                base_voice = voice_by_id.get(audio_entry.get("voice_id"))
            base_voice = base_voice or primary_voice or {}
            audio_variants.append(
                {
                    "key": base_voice.get("key", "original"),
                    "name": base_voice.get("name", "Original voice"),
                    "gender": base_voice.get("gender"),
                    "accent": base_voice.get("accent"),
                    "audio": audio_url,
                    "primary": True,
                }
            )

        sentence_variants = variant_items.get(sentence_id, {})
        if sentence_variants is not None and not isinstance(sentence_variants, dict):
            raise ValueError(f"Invalid voice variants for {sentence_id}")
        for voice_key, variant in (sentence_variants or {}).items():
            if not isinstance(variant, dict):
                continue
            filename = variant.get("audio_file")
            if not isinstance(filename, str) or not filename:
                continue
            audio_path = audio_directory / filename
            if not audio_path.is_file() or audio_path.stat().st_size < 100:
                continue
            voice = voice_by_id.get(variant.get("voice_id"), {})
            audio_variants.append(
                {
                    "key": voice.get("key", voice_key),
                    "name": voice.get("name", voice_key),
                    "gender": voice.get("gender"),
                    "accent": voice.get("accent"),
                    "audio": f"/audio/{filename}",
                    "primary": False,
                }
            )
            variant_audio_count += 1

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
                "audio_variants": audio_variants,
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
        "variant_audio_count": variant_audio_count,
        "sentences": app_sentences,
    }


def main() -> int:
    args = parse_args()
    deck_path = args.deck.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    variants_manifest_path = args.variants_manifest.expanduser().resolve()
    voices_path = args.voices.expanduser().resolve()
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

    variants_manifest = (
        read_json(variants_manifest_path)
        if variants_manifest_path.exists()
        else {"version": 1, "items": {}}
    )
    voice_catalog = (
        read_json(voices_path)
        if voices_path.exists()
        else {"version": 1, "voices": []}
    )
    if not isinstance(variants_manifest, dict) or not isinstance(voice_catalog, dict):
        raise ValueError("Voice catalog and variants manifest must be JSON objects")

    bundle = build_bundle(
        deck,
        manifest,
        audio_directory,
        args.allow_missing_audio,
        variants_manifest,
        voice_catalog,
    )
    atomic_write_json(output, bundle)
    print(
        f"Built {bundle['sentence_count']} app entries "
        f"({bundle['missing_audio_count']} missing audio, "
        f"{bundle['variant_audio_count']} additional speaker files)."
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
