#!/usr/bin/env python3
"""Merge the Berlitz 3, 4, and 5 app decks into the default app."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from common import PROJECT_ROOT, atomic_write_json, read_json, utc_timestamp


DEFAULT_COLLECTION_SOURCES = (
    (
        3,
        PROJECT_ROOT / "collections" / "berlitz3" / "dist" / "deck.json",
        PROJECT_ROOT / "collections" / "berlitz3" / "audio",
    ),
    (
        4,
        PROJECT_ROOT / "collections" / "berlitz4" / "dist" / "deck.json",
        PROJECT_ROOT / "collections" / "berlitz4" / "audio",
    ),
)
DEFAULT_OUTPUT = PROJECT_ROOT / "dist" / "deck.json"
DEFAULT_AUDIO_OUTPUT = PROJECT_ROOT / "audio"
DEFAULT_LEVEL5_SNAPSHOT = PROJECT_ROOT / "build" / "berlitz5-app-deck.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge all three Berlitz levels into the default local app."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audio-output", type=Path, default=DEFAULT_AUDIO_OUTPUT)
    return parser.parse_args()


def audio_filename(audio_url: Any, sentence_id: str) -> str:
    if not isinstance(audio_url, str) or not audio_url.startswith("/audio/"):
        raise ValueError(f"{sentence_id} has an invalid audio URL")
    filename = audio_url.removeprefix("/audio/")
    if not filename or Path(filename).name != filename or not filename.endswith(".mp3"):
        raise ValueError(f"{sentence_id} has an unsafe audio filename")
    return filename


def map_audio(
    audio_url: Any,
    *,
    sentence_id: str,
    level: int,
    source_directory: Path,
) -> str:
    filename = audio_filename(audio_url, sentence_id)
    source = source_directory / filename
    if not source.is_file() or source.stat().st_size < 100:
        raise FileNotFoundError(f"Missing audio for {sentence_id}: {source}")

    # Imported audio stays in its existing collection directory. The server
    # resolves these namespaced URLs without copying the MP3 files.
    prefix = "" if level == 5 else f"berlitz{level}/"
    return f"/audio/{prefix}{filename}"


def merge_decks(
    sources: tuple[tuple[int, Path, Path], ...],
) -> dict[str, Any]:
    merged_sentences: list[dict[str, Any]] = []
    level_counts: dict[str, int] = {}

    for level, deck_path, audio_directory in sources:
        deck = read_json(deck_path)
        sentences = deck.get("sentences") if isinstance(deck, dict) else None
        if not isinstance(sentences, list) or not sentences:
            raise ValueError(f"Level {level} deck is empty: {deck_path}")

        for raw_sentence in sentences:
            if not isinstance(raw_sentence, dict):
                raise ValueError(f"Level {level} contains an invalid sentence")
            sentence = deepcopy(raw_sentence)
            original_id = sentence.get("id")
            if not isinstance(original_id, str) or not original_id:
                raise ValueError(f"Level {level} contains a sentence without an ID")

            # Existing Level 5 IDs stay untouched so current progress remains valid.
            sentence["id"] = (
                original_id if level == 5 else f"berlitz{level}-{original_id}"
            )
            sentence["level"] = level
            sentence["audio"] = map_audio(
                sentence.get("audio"),
                sentence_id=original_id,
                level=level,
                source_directory=audio_directory,
            )

            variants = sentence.get("audio_variants", [])
            if not isinstance(variants, list):
                raise ValueError(f"{original_id} has invalid audio variants")
            for variant in variants:
                if not isinstance(variant, dict):
                    raise ValueError(f"{original_id} has an invalid audio variant")
                variant["audio"] = map_audio(
                    variant.get("audio"),
                    sentence_id=original_id,
                    level=level,
                    source_directory=audio_directory,
                )

            for source in sentence.get("sources", []):
                if isinstance(source, dict):
                    source["level"] = level

            merged_sentences.append(sentence)

        level_counts[str(level)] = len(sentences)

    ids = [sentence["id"] for sentence in merged_sentences]
    if len(ids) != len(set(ids)):
        raise ValueError("Merged deck still contains duplicate sentence IDs")

    missing_audio = sum(1 for sentence in merged_sentences if not sentence.get("audio"))
    variant_audio_count = sum(
        max(0, len(sentence.get("audio_variants", [])) - 1)
        for sentence in merged_sentences
    )
    return {
        "version": 1,
        "built_at": utc_timestamp(),
        "sentence_count": len(merged_sentences),
        "missing_audio_count": missing_audio,
        "variant_audio_count": variant_audio_count,
        "level_counts": level_counts,
        "sentences": merged_sentences,
    }


def prepare_level5_snapshot(output: Path, snapshot: Path) -> Path:
    """Keep the pre-merge Level 5 deck available across repeatable rebuilds."""
    if output.exists():
        current = read_json(output)
        if not isinstance(current, dict):
            raise ValueError(f"Invalid default deck: {output}")
        if "level_counts" not in current:
            # The normal Level 5 pipeline has just rebuilt the default deck.
            # Refresh the snapshot before the unified deck replaces it.
            atomic_write_json(snapshot, current)
        elif not snapshot.exists():
            # Recover the snapshot if an already-merged deck is present but the
            # ignored build directory was cleaned.
            sentences = current.get("sentences", [])
            level5_sentences = [
                deepcopy(sentence)
                for sentence in sentences
                if isinstance(sentence, dict) and sentence.get("level") == 5
            ]
            if not level5_sentences:
                raise ValueError("Merged deck contains no Level 5 sentences")
            recovered = {
                "version": 1,
                "built_at": current.get("built_at", utc_timestamp()),
                "sentence_count": len(level5_sentences),
                "missing_audio_count": 0,
                "variant_audio_count": sum(
                    max(0, len(sentence.get("audio_variants", [])) - 1)
                    for sentence in level5_sentences
                ),
                "sentences": level5_sentences,
            }
            atomic_write_json(snapshot, recovered)
    if not snapshot.exists():
        raise FileNotFoundError(
            "No Level 5 app deck is available. Run scripts/build_app_data.py first."
        )
    return snapshot


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    audio_output = args.audio_output.expanduser().resolve()
    level5_snapshot = prepare_level5_snapshot(output, DEFAULT_LEVEL5_SNAPSHOT)
    sources = tuple(
        (level, deck.expanduser().resolve(), audio.expanduser().resolve())
        for level, deck, audio in (
            *DEFAULT_COLLECTION_SOURCES,
            (5, level5_snapshot, audio_output),
        )
    )
    bundle = merge_decks(sources)
    atomic_write_json(output, bundle)
    counts = bundle["level_counts"]
    print(
        f"Merged {bundle['sentence_count']} drills "
        f"(Level 3: {counts['3']}, Level 4: {counts['4']}, Level 5: {counts['5']})."
    )
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
