#!/usr/bin/env python3
"""Validate, deduplicate, and compile per-lesson Codex sentence batches."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from common import (
    BUILD_DIR,
    GENERATED_DIR,
    PROJECT_ROOT,
    atomic_write_json,
    normalize_chinese,
    read_json,
    require_string,
    require_string_list,
    selected_lessons,
    sentence_id,
    utc_timestamp,
)


DEFAULT_OUTPUT = BUILD_DIR / "sentences.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile per-lesson Codex output into a stable sentence deck."
    )
    parser.add_argument(
        "--input-directory",
        type=Path,
        default=GENERATED_DIR,
        help="Directory containing YYYY-MM-DD.json batches",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Compiled deck path",
    )
    return parser.parse_args()


def validate_candidate(value: Any, lesson: str, index: int) -> dict[str, Any]:
    prefix = f"{lesson} sentence {index}"
    if not isinstance(value, dict):
        raise ValueError(f"{prefix} must be an object")

    chinese = require_string(value.get("chinese"), f"{prefix}.chinese")
    pinyin = require_string(value.get("pinyin"), f"{prefix}.pinyin")
    english_hint = require_string(
        value.get("english_hint"), f"{prefix}.english_hint"
    )
    scenario = require_string(value.get("scenario"), f"{prefix}.scenario")
    focus = require_string_list(value.get("focus"), f"{prefix}.focus")
    source_note = require_string(value.get("source_note"), f"{prefix}.source_note")
    priority = value.get("priority")
    if not isinstance(priority, int) or not 1 <= priority <= 5:
        raise ValueError(f"{prefix}.priority must be an integer from 1 to 5")

    return {
        "chinese": chinese,
        "pinyin": pinyin,
        "english_hint": english_hint,
        "scenario": scenario,
        "tts_text": chinese,
        "focus": focus,
        "priority": priority,
        "default_repetitions": 3,
        "sources": [
            {
                "lesson": lesson,
                "analysis_file": f"{lesson}-04-transcription-analysis.txt",
                "transcript_file": f"{lesson}-02-transcription.txt",
                "note": source_note,
            }
        ],
    }


def merge_candidate(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing["priority"] = max(existing["priority"], incoming["priority"])
    existing["focus"] = list(dict.fromkeys(existing["focus"] + incoming["focus"]))
    existing["sources"].extend(incoming["sources"])

    # Prefer the most informative cue while retaining a deterministic result.
    if len(incoming["scenario"]) > len(existing["scenario"]):
        existing["scenario"] = incoming["scenario"]
    if len(incoming["english_hint"]) > len(existing["english_hint"]):
        existing["english_hint"] = incoming["english_hint"]


def compile_batches(input_directory: Path) -> dict[str, Any]:
    expected_lessons = selected_lessons()
    batches: list[tuple[str, dict[str, Any]]] = []
    missing: list[str] = []
    for lesson in expected_lessons:
        path = input_directory / f"{lesson}.json"
        if not path.is_file():
            missing.append(lesson)
            continue
        value = read_json(path)
        if not isinstance(value, dict) or value.get("lesson") != lesson:
            raise ValueError(f"Invalid or mismatched lesson batch: {path}")
        batches.append((lesson, value))

    if missing:
        raise FileNotFoundError(
            "Missing generated lesson batches: "
            + ", ".join(missing)
            + ". Run generate_sentences.py first."
        )

    by_normalized_chinese: dict[str, dict[str, Any]] = {}
    raw_count = 0
    for lesson, batch in batches:
        sentences = batch.get("sentences")
        if not isinstance(sentences, list) or not sentences:
            raise ValueError(f"Lesson {lesson} has no sentences")
        for index, raw_candidate in enumerate(sentences, start=1):
            raw_count += 1
            candidate = validate_candidate(raw_candidate, lesson, index)
            key = normalize_chinese(candidate["chinese"])
            if not key:
                raise ValueError(f"Lesson {lesson} sentence {index} has no Chinese text")
            if key in by_normalized_chinese:
                merge_candidate(by_normalized_chinese[key], candidate)
            else:
                candidate["id"] = sentence_id(candidate["chinese"])
                by_normalized_chinese[key] = candidate

    sentences = list(by_normalized_chinese.values())
    sentences.sort(
        key=lambda item: (
            -item["priority"],
            item["sources"][0]["lesson"],
            item["id"],
        )
    )
    return {
        "version": 1,
        "generated_at": utc_timestamp(),
        "source_lessons": expected_lessons,
        "raw_sentence_count": raw_count,
        "sentence_count": len(sentences),
        "sentences": sentences,
    }


def main() -> int:
    args = parse_args()
    input_directory = args.input_directory.expanduser().resolve()
    output = args.output.expanduser().resolve()
    deck = compile_batches(input_directory)
    atomic_write_json(output, deck)
    print(
        f"Compiled {deck['raw_sentence_count']} candidates into "
        f"{deck['sentence_count']} unique sentences."
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

