#!/usr/bin/env python3
"""Generate per-lesson Mandarin drills through non-interactive Codex CLI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import (
    GENERATED_DIR,
    PROJECT_ROOT,
    PROMPT_DIR,
    SCHEMA_DIR,
    atomic_write_json,
    lesson_paths,
    selected_lessons,
    utc_timestamp,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use Codex to turn Berlitz lesson sources into sentence drills."
    )
    parser.add_argument(
        "--lesson",
        action="append",
        default=[],
        help="Only process this YYYY-MM-DD lesson; repeat for multiple lessons",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing per-lesson generated JSON",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and show work without calling Codex",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("CODEX_MODEL"),
        help="Optional Codex model override (default: current CLI default)",
    )
    parser.add_argument(
        "--codex-command",
        default=os.environ.get("CODEX_COMMAND", "codex"),
        help="Codex executable (default: codex)",
    )
    return parser.parse_args()


def build_prompt(lesson: str, transcript: Path, analysis: Path) -> str:
    instructions = (PROMPT_DIR / "generate_sentences.txt").read_text(
        encoding="utf-8"
    )
    transcript_text = (
        transcript.read_text(encoding="utf-8-sig")
        if transcript.is_file()
        else "[No raw transcript is available for this lesson. Use only the analysis.]"
    )
    analysis_text = analysis.read_text(encoding="utf-8-sig")
    return (
        f"{instructions.rstrip()}\n\n"
        f"The required lesson field is: {lesson}\n\n"
        "--- BEGIN LESSON ANALYSIS ---\n\n"
        f"{analysis_text.rstrip()}\n\n"
        "--- END LESSON ANALYSIS ---\n\n"
        "--- BEGIN RAW TRANSCRIPT ---\n\n"
        f"{transcript_text.rstrip()}\n\n"
        "--- END RAW TRANSCRIPT ---\n"
    )


def validate_batch(value: object, lesson: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Codex output must be a JSON object")
    if value.get("lesson") != lesson:
        raise ValueError(
            f"Codex output lesson is {value.get('lesson')!r}; expected {lesson!r}"
        )
    sentences = value.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        raise ValueError("Codex output must contain at least one sentence")

    chinese_seen: set[str] = set()
    for index, sentence in enumerate(sentences, start=1):
        if not isinstance(sentence, dict):
            raise ValueError(f"Sentence {index} is not an object")
        chinese = sentence.get("chinese")
        if not isinstance(chinese, str) or not chinese.strip():
            raise ValueError(f"Sentence {index} has no Chinese text")
        if chinese in chinese_seen:
            raise ValueError(f"Duplicate sentence in {lesson}: {chinese}")
        chinese_seen.add(chinese)
        priority = sentence.get("priority")
        if not isinstance(priority, int) or not 1 <= priority <= 5:
            raise ValueError(f"Sentence {index} has invalid priority: {priority}")
    return value


def run_codex(
    codex_command: str,
    prompt: str,
    output_path: Path,
    model: str | None,
) -> None:
    schema_path = (SCHEMA_DIR / "codex_sentence_batch.schema.json").resolve()
    with tempfile.TemporaryDirectory(prefix="chinese-drill-codex-") as temp_name:
        temp_directory = Path(temp_name)
        raw_output = temp_directory / "result.json"
        command = [
            codex_command,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--cd",
            str(temp_directory),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(raw_output),
        ]
        if model:
            command.extend(["--model", model])
        command.append("-")

        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            details = result.stderr.strip()[-4000:]
            raise RuntimeError(
                f"Codex failed with exit code {result.returncode}.\n{details}"
            )
        if not raw_output.is_file() or raw_output.stat().st_size == 0:
            raise RuntimeError("Codex completed without writing a result")

        try:
            value = json.loads(raw_output.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Codex returned invalid JSON: {error}") from error

        lesson = output_path.stem
        validated = validate_batch(value, lesson)
        validated["generated_at"] = utc_timestamp()
        validated["generator"] = "codex-cli"
        if model:
            validated["requested_model"] = model
        atomic_write_json(output_path, validated)


def main() -> int:
    args = parse_args()
    lessons = selected_lessons(args.lesson)
    if not args.dry_run and shutil.which(args.codex_command) is None:
        raise FileNotFoundError(
            f"Codex executable not found: {args.codex_command}. Install or configure "
            "the Codex CLI first."
        )

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    processed = 0
    skipped = 0
    for index, lesson in enumerate(lessons, start=1):
        transcript, analysis = lesson_paths(lesson)
        output_path = GENERATED_DIR / f"{lesson}.json"
        if output_path.exists() and not args.force:
            print(f"[{index}/{len(lessons)}] skip {lesson}: output exists")
            skipped += 1
            continue

        prompt = build_prompt(lesson, transcript, analysis)
        if args.dry_run:
            print(
                f"[{index}/{len(lessons)}] would generate {lesson}: "
                f"{len(prompt):,} prompt characters -> {output_path.relative_to(PROJECT_ROOT)}"
            )
            processed += 1
            continue

        print(f"[{index}/{len(lessons)}] generating {lesson}...", flush=True)
        run_codex(args.codex_command, prompt, output_path, args.model)
        count = len(json.loads(output_path.read_text(encoding="utf-8"))["sentences"])
        print(f"             wrote {count} sentences")
        processed += 1

    print(f"Done: {processed} processed, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
