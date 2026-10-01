# Chinese Drill App

A small, local-first speaking drill app built from the learner's Berlitz 5
lesson transcripts and evaluations.

The app's job is deliberately narrow:

1. Turn recurring mistakes and useful personal topics into short, natural
   Mandarin sentences.
2. Generate and cache one native-quality audio file per sentence.
3. Run short practice sessions in which each sentence is heard and repeated
   two or three times.
4. Remember which sentence patterns need more practice.

## Current status

The Python content pipeline is implemented, the Berlitz 5 source set is
inventoried, and a small pilot deck demonstrates the proposed sentence format.
No Codex generation or ElevenLabs synthesis requests have been made yet.

## Proposed MVP

- Local responsive web app, launched with one command.
- Audio-first cards with Chinese hidden initially.
- Two or three repetitions per sentence, configurable per session.
- Reveal controls for simplified Chinese, pinyin, and a short English hint.
- Keyboard controls: space to replay, enter to advance, and number keys to rate.
- Daily queue biased toward high-priority recurring errors.
- Cached MP3 audio so normal practice makes no API calls.
- Progress saved atomically to a local JSON file after every rating; no account
  or cloud service required.

## Project layout

```text
chinese-drill-app/
  README.md
  .env.example
  data/
    sources.json
    sentences.sample.json
    generated/             # Checkpointed Codex output, one file per lesson
  docs/
    PRODUCT_DESIGN.md
    CONTENT_PIPELINE.md
  prompts/
    generate_sentences.txt
  schemas/
    codex_sentence_batch.schema.json
  audio/                 # Generated files; ignored by git
  build/                 # Compiled deck and audio manifest
  dist/                  # Final JSON consumed by the future app
  scripts/               # Pipeline tools
  tests/
  web/                   # Practice UI (next milestone)
```

## Inputs

The initial source set is the 15 transcript/evaluation pairs in:

```text
../Berlitz5/records_and_analysis/
```

Evaluations are the primary source for corrected Mandarin. Transcripts provide
personal context and evidence that an error recurs. Raw learner errors must
never be sent directly to text-to-speech.

## Pipeline commands

Run commands from this project directory.

```bash
# Inspect all stages without making network calls.
python3 scripts/run_pipeline.py --dry-run

# Stage 1: ask Codex to process all 15 transcript/evaluation pairs.
python3 scripts/generate_sentences.py

# Stage 2: validate and deduplicate the lesson results.
python3 scripts/compile_deck.py

# Stage 3: generate only missing or changed ElevenLabs audio.
python3 scripts/synthesize_audio.py

# Stage 4: combine sentences and audio into app-ready JSON.
python3 scripts/build_app_data.py

# Or run every stage in sequence.
python3 scripts/run_pipeline.py
```

Generation is checkpointed by lesson. Rerunning Stage 1 skips completed dates
unless `--force` is supplied. Audio is cached by sentence text, voice, model,
language, and output format.

To test a voice without generating the entire deck:

```bash
python3 scripts/synthesize_audio.py --limit 8
```

Copy `.env.example` to `.env`, add the ElevenLabs key and a Mandarin-native
voice ID, then keep `.env` private. Codex uses the existing Codex CLI login.

## Requirements

- Python 3.10 or newer; the pipeline itself has no Python package dependencies.
- Codex CLI installed and logged in for sentence generation.
- ElevenLabs API key and voice ID for audio synthesis.

Run local tests with:

```bash
python3 -m unittest discover -s tests -v
```

See [PRODUCT_DESIGN.md](docs/PRODUCT_DESIGN.md) for the experience and
[CONTENT_PIPELINE.md](docs/CONTENT_PIPELINE.md) for extraction and quality
rules. The future practice server will also be Python standard library code,
so launching it will not require Flask, FastAPI, Node, or a frontend build.
