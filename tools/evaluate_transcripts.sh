#!/usr/bin/env bash

# Evaluate lesson transcripts one at a time with a fresh Codex session.
#
# Usage:
#   tools/evaluate_transcripts.sh [--background] [--dry-run] [--force] \
#     /path/to/evaluation-folder /full/path/to/prompt.txt
#
# Input files must be named:
#   YYYY-MM-DD-02-transcription.txt
#
# Each result is written beside its transcript as:
#   YYYY-MM-DD-04-transcription-analysis.txt

set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  evaluate_transcripts.sh [--background] [--dry-run] [--force] EVALUATION_FOLDER PROMPT_FILE

Arguments:
  EVALUATION_FOLDER  Folder containing YYYY-MM-DD-02-transcription.txt files.
  PROMPT_FILE        Path to the complete evaluation prompt.

Options:
  --background       Run detached and write progress to transcript-evaluations.log.
  --dry-run          Show what would run without invoking Codex or writing files.
  --force            Replace analysis files that already exist.
  -h, --help         Show this help message.

Example:
  tools/evaluate_transcripts.sh \
    "$(pwd)/Berlitz5/records_and_analysis" \
    "$(pwd)/prompt.txt"
EOF
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

dry_run=false
force=false
background=false

while (($# > 0)); do
  case "$1" in
    --background)
      background=true
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --force)
      force=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      fail "Unknown option: $1"
      ;;
    *)
      break
      ;;
  esac
done

(($# == 2)) || {
  usage >&2
  exit 2
}

evaluation_folder=$1
prompt_file=$2

[[ -d "$evaluation_folder" ]] || fail "Evaluation folder not found: $evaluation_folder"
[[ -f "$prompt_file" ]] || fail "Prompt file not found: $prompt_file"
[[ -r "$prompt_file" ]] || fail "Prompt file is not readable: $prompt_file"

evaluation_folder=$(cd "$evaluation_folder" && pwd -P)
prompt_directory=$(cd "$(dirname "$prompt_file")" && pwd -P)
prompt_file="$prompt_directory/$(basename "$prompt_file")"

if [[ "$background" == true ]]; then
  [[ "$dry_run" == false ]] || fail "--background and --dry-run cannot be used together"

  script_directory=$(cd "$(dirname "$0")" && pwd -P)
  script_path="$script_directory/$(basename "$0")"
  log_file="$evaluation_folder/transcript-evaluations.log"
  background_args=()
  if [[ "$force" == true ]]; then
    background_args+=(--force)
  fi

  nohup "$script_path" "${background_args[@]}" "$evaluation_folder" "$prompt_file" \
    </dev/null >>"$log_file" 2>&1 &
  background_pid=$!

  printf 'Started transcript evaluations in the background (PID %d).\n' "$background_pid"
  printf 'Progress log: %s\n' "$log_file"
  exit 0
fi

if [[ "$dry_run" == false ]]; then
  command -v codex >/dev/null 2>&1 || fail "The 'codex' command is not installed or not in PATH"
fi

# Bash expands this glob in lexical order, which is chronological for the
# YYYY-MM-DD prefix. nullglob prevents a missing match from becoming a literal.
export LC_ALL=C
shopt -s nullglob
transcripts=("$evaluation_folder"/????-??-??-02-transcription.txt)
shopt -u nullglob

((${#transcripts[@]} > 0)) || fail \
  "No YYYY-MM-DD-02-transcription.txt files found in: $evaluation_folder"

current_temp_dir=''
current_output_tmp=''
current_log_file=''

cleanup() {
  if [[ -n "$current_output_tmp" && -f "$current_output_tmp" ]]; then
    rm -f -- "$current_output_tmp"
  fi
  if [[ -n "$current_log_file" && -f "$current_log_file" ]]; then
    rm -f -- "$current_log_file"
  fi
  if [[ -n "$current_temp_dir" && -d "$current_temp_dir" ]]; then
    rmdir -- "$current_temp_dir" 2>/dev/null || true
  fi
}

trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

processed=0
skipped=0
total=${#transcripts[@]}

for transcript in "${transcripts[@]}"; do
  transcript_name=$(basename "$transcript")
  lesson_date=${transcript_name%-02-transcription.txt}

  if [[ ! "$lesson_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    printf 'Skipping unexpected filename: %s\n' "$transcript_name" >&2
    ((skipped += 1))
    continue
  fi

  output_file="$evaluation_folder/$lesson_date-04-transcription-analysis.txt"

  if [[ -e "$output_file" && "$force" == false ]]; then
    printf '[skip] %s already exists\n' "$(basename "$output_file")"
    ((skipped += 1))
    continue
  fi

  printf '[%d/%d] Evaluating %s\n' "$((processed + skipped + 1))" "$total" "$transcript_name"

  if [[ "$dry_run" == true ]]; then
    printf '        -> %s\n' "$(basename "$output_file")"
    ((processed += 1))
    continue
  fi

  current_temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/transcript-evaluation.XXXXXX")
  current_log_file=$(mktemp "${TMPDIR:-/tmp}/transcript-evaluation-log.XXXXXX")
  current_output_tmp="$evaluation_folder/.$lesson_date-04-transcription-analysis.txt.tmp.$$"
  rm -f -- "$current_output_tmp"

  # codex exec is synchronous: this pipeline must finish before the loop can
  # advance to the next transcript. A clean temporary working directory and an
  # ephemeral session prevent project and previous-run context from carrying in.
  # Codex's stdout/stderr stream is captured so only this script's concise
  # progress appears in the terminal.
  if ! {
    printf '%s\n\n' 'Follow the evaluation instructions below exactly.'
    cat -- "$prompt_file"
    printf '\n\n--- BEGIN LESSON TRANSCRIPT ---\n\n'
    cat -- "$transcript"
    printf '\n\n--- END LESSON TRANSCRIPT ---\n'
    printf '%s\n' \
      'Execution constraint: Use only the instructions and transcript in this message.' \
      'Do not use tools, run commands, read files, or inspect previous analyses.' \
      'If the evaluation instructions request previous files, ignore that request.' \
      'Return only the finished transcript analysis.'
  } | codex exec \
        --ephemeral \
        --ignore-user-config \
        --skip-git-repo-check \
        --sandbox read-only \
        --cd "$current_temp_dir" \
        --output-last-message "$current_output_tmp" \
        - >"$current_log_file" 2>&1; then
    printf 'Codex details:\n' >&2
    tail -n 50 "$current_log_file" >&2 || true
    rm -f -- "$current_output_tmp"
    current_output_tmp=''
    rm -f -- "$current_log_file"
    current_log_file=''
    rmdir -- "$current_temp_dir" 2>/dev/null || true
    current_temp_dir=''
    fail "Codex evaluation failed for: $transcript_name"
  fi

  if [[ ! -s "$current_output_tmp" ]]; then
    printf 'Codex details:\n' >&2
    tail -n 50 "$current_log_file" >&2 || true
    fail "Codex produced no analysis for: $transcript_name"
  fi

  mv -f -- "$current_output_tmp" "$output_file"
  current_output_tmp=''
  rm -f -- "$current_log_file"
  current_log_file=''
  rmdir -- "$current_temp_dir" 2>/dev/null || true
  current_temp_dir=''

  ((processed += 1))
  printf '        -> %s\n' "$(basename "$output_file")"
done

printf 'Done. Evaluated: %d; skipped: %d; total: %d\n' \
  "$processed" "$skipped" "$total"
