#!/usr/bin/env python3
"""Run the complete content pipeline with one Python command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate drills, compile them, synthesize audio, and build app data."
    )
    parser.add_argument(
        "--lesson",
        action="append",
        default=[],
        help="Regenerate only this lesson in the Codex stage; repeat as needed",
    )
    parser.add_argument("--model", help="Optional Codex model override")
    parser.add_argument(
        "--force-sentences",
        action="store_true",
        help="Regenerate existing Codex lesson batches",
    )
    parser.add_argument(
        "--force-audio",
        action="store_true",
        help="Regenerate audio even when its hash is cached",
    )
    parser.add_argument(
        "--audio-limit", type=int, help="Generate at most N missing audio files"
    )
    parser.add_argument(
        "--skip-codex", action="store_true", help="Use existing generated batches"
    )
    parser.add_argument(
        "--skip-audio", action="store_true", help="Do not call ElevenLabs"
    )
    parser.add_argument(
        "--allow-missing-audio",
        action="store_true",
        help="Allow the final app bundle to contain null audio paths",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print stage commands without running them"
    )
    return parser.parse_args()


def display_command(command: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(part) for part in command)


def run_stage(name: str, command: list[str], dry_run: bool) -> None:
    print(f"\n== {name} ==", flush=True)
    if dry_run:
        print(display_command(command))
        return
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{name} failed with exit code {result.returncode}")


def main() -> int:
    args = parse_args()
    python = sys.executable

    generate = [python, str(SCRIPT_DIR / "generate_sentences.py")]
    for lesson in args.lesson:
        generate.extend(["--lesson", lesson])
    if args.model:
        generate.extend(["--model", args.model])
    if args.force_sentences:
        generate.append("--force")

    compile_command = [python, str(SCRIPT_DIR / "compile_deck.py")]

    audio = [python, str(SCRIPT_DIR / "synthesize_audio.py")]
    if args.force_audio:
        audio.append("--force")
    if args.audio_limit is not None:
        audio.extend(["--limit", str(args.audio_limit)])

    build = [python, str(SCRIPT_DIR / "build_app_data.py")]
    if args.allow_missing_audio or args.skip_audio:
        build.append("--allow-missing-audio")

    if not args.skip_codex:
        run_stage("Generate sentences with Codex", generate, args.dry_run)
    run_stage("Compile and deduplicate", compile_command, args.dry_run)
    if not args.skip_audio:
        run_stage("Generate ElevenLabs audio", audio, args.dry_run)
    run_stage("Build app data", build, args.dry_run)

    print("\nPipeline complete." if not args.dry_run else "\nDry run complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)

