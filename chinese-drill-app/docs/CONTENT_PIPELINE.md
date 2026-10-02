# Content pipeline

This document explains how lesson transcripts and analyses become the 696-card
runtime deck and its 2,088 reference MP3s.

## Source collections

| Level | Lesson dates | Lessons | Source configuration | Final drills |
| --- | --- | ---: | --- | ---: |
| Berlitz 3 | 2026-01-07 to 2026-03-14 | 18 | `collections/berlitz3/data/sources.json` | 244 |
| Berlitz 4 | 2026-03-30 to 2026-06-08 | 18 | `collections/berlitz4/data/sources.json` | 250 |
| Berlitz 5 | 2026-07-08 to 2026-09-30 | 15 | `data/sources.json` | 202 |

Each source configuration names the source directory, lesson dates, transcript
suffix, analysis suffix, and whether transcripts are optional. The normal file
pair is:

```text
YYYY-MM-DD-02-transcription.txt
YYYY-MM-DD-04-transcription-analysis.txt
```

The analysis is the authority for corrected Mandarin. The transcript supplies
the learner's intent, personal context, timestamps, and evidence that an error
recurs. Incorrect raw learner sentences must not be sent directly to TTS.

## Collection isolation

The same scripts serve all levels. Setting `CHINESE_DRILL_COLLECTION_DIR`,
normally through `run_pipeline.py --collection`, redirects these directories:

```text
data/
build/
audio/
dist/
```

Therefore Level 3 and 4 can be generated or repaired without overwriting Level
5 or one another. Prompts and schemas remain shared at the project root.

## Stage 1: structured sentence generation

`scripts/generate_sentences.py` invokes `codex exec` once per selected lesson.
It combines the transcript, analysis, shared prompt, and JSON Schema. Output is
checkpointed as one file per lesson:

```text
data/generated/YYYY-MM-DD.json
collections/berlitz3/data/generated/YYYY-MM-DD.json
collections/berlitz4/data/generated/YYYY-MM-DD.json
```

Completed lessons are skipped unless `--force` is supplied. This makes a long
run resumable and prevents a connection failure from discarding earlier work.
`--lesson YYYY-MM-DD` limits generation to particular dates.

Each candidate contains:

- Correct simplified Chinese and tone-marked pinyin
- A short English hint and scenario cue
- Focus tags and a 1–5 priority
- Default repetition count
- Source filenames, lesson date, and an explanatory note

Candidate families usually include one personal sentence, one controlled
variation, and optionally a useful question or negative form. Sentences are
normally short enough to speak in roughly two to five seconds.

## Stage 2: validation and compilation

`scripts/compile_deck.py` reads every checkpoint for the collection, validates
the contract, normalizes punctuation and whitespace, deduplicates exact Chinese
sentences, merges source/focus metadata, and writes:

```text
build/sentences.json
```

Stable sentence IDs are the first 12 hexadecimal characters of a SHA-256 hash
of normalized Chinese, prefixed with `sentence-`. The same sentence therefore
gets the same collection-level ID on repeat builds.

Priority guidance:

- 5: recurring in at least three lessons
- 4: repeated error or essential HSK 3 structure
- 3: useful personal phrase seen once
- 2: useful but less urgent variation
- 1: recognition-only or optional material

## Stage 3: ElevenLabs reference audio

`scripts/synthesize_audio.py` renders the primary speaker. The current request
configuration is:

- Model: `eleven_v4`
- Language: `zh`
- Output: `mp3_44100_128`
- Primary voice: Mr. Chen, male Beijing Mandarin

`scripts/synthesize_voice_variants.py` renders the two non-primary voices from
the collection's `data/voices.json`:

- Chen, female Taiwan Mandarin
- Anna Su, female Taiwan Mandarin

Audio generation is incremental. A content hash includes the spoken text,
voice, model, language, and output settings. If the matching MP3 already exists
and is complete, the script reuses it. Successful calls are recorded in JSON
manifests under `build/`, so reruns request only missing or changed audio.

The scripts retry transient failures. On macOS they use the system `curl`
transport so TLS validation follows Keychain certificates; certificate
verification is never disabled. Temporary files are replaced only after a
successful response.

## Stage 4: per-level app bundle

`scripts/build_app_data.py` combines the compiled sentences, primary audio
manifest, variant manifest, and voice catalog. It checks every MP3 and fails on
missing audio unless `--allow-missing-audio` is explicitly supplied. The output
is the collection's `dist/deck.json`.

Each runtime sentence includes:

```text
id, chinese, pinyin, english_hint, scenario, focus, priority,
default_repetitions, sources, audio, audio_variants
```

`audio_variants` contains speaker key, display name, gender, accent, URL, and a
primary flag.

## Stage 5: unified deck

`scripts/merge_levels.py` merges the three per-level bundles into the default
`dist/deck.json`.

Important merge behavior:

1. Level 5 IDs remain unchanged so existing Level 5 progress continues to
   match.
2. Level 3 and 4 IDs receive `berlitz3-` or `berlitz4-` prefixes. This preserves
   all cards even when identical Chinese exists in multiple levels.
3. Every card receives a numeric `level` field, and every source receives its
   level for display and traceability.
4. Level 3/4 MP3s are not copied. Their URLs become
   `/audio/berlitz3/<file>` or `/audio/berlitz4/<file>`, and the local server
   resolves those namespaces to the collection audio directories.
5. Before a merge replaces the Level 5 bundle, it keeps
   `build/berlitz5-app-deck.json`. This makes repeated merges idempotent. If the
   Level 5 pipeline rebuilds the default deck, the next merge refreshes that
   snapshot automatically.
6. The merger rejects duplicate final IDs and missing/incomplete audio.

The current result is 696 unique cards, three voices per card, and no missing
audio.

## Complete commands

```bash
# Inspect the default/Level 5 stages without making network calls.
python3 scripts/run_pipeline.py --dry-run

# Level 3: all stages and all speakers.
python3 scripts/run_pipeline.py \
  --collection collections/berlitz3 \
  --speaker-variants

# Level 4: all stages and all speakers.
python3 scripts/run_pipeline.py \
  --collection collections/berlitz4 \
  --speaker-variants

# Level 5: all stages and all speakers.
python3 scripts/run_pipeline.py --speaker-variants

# Rebuild the unified application deck afterward.
python3 scripts/merge_levels.py

# Validate the final deck and all resolved MP3 paths.
python3 app.py --check
```

Useful recovery controls:

```bash
# Reuse existing Codex checkpoint JSON and start at compilation/audio.
python3 scripts/run_pipeline.py --skip-codex --speaker-variants

# Compile/build without calling ElevenLabs.
python3 scripts/run_pipeline.py --skip-codex --skip-audio

# Limit new primary and variant requests while testing.
python3 scripts/run_pipeline.py --skip-codex --speaker-variants --audio-limit 8

# Regenerate one lesson's structured candidates.
python3 scripts/run_pipeline.py --lesson 2026-09-30 --force-sentences
```

## Data flow

```text
transcripts + lesson analyses
              ↓
Codex structured extraction (checkpointed per lesson)
              ↓
data/generated/YYYY-MM-DD.json
              ↓
validation + exact-sentence deduplication
              ↓
build/sentences.json
              ↓
ElevenLabs primary + two voice variants
              ↓
audio/*.mp3 + build/audio[-variants]-manifest.json
              ↓
per-level dist/deck.json
              ↓
scripts/merge_levels.py
              ↓
unified dist/deck.json
              ↓
local practice app
```

## Generated data and Git

`build/*.json`, `dist/*.json`, collection build/dist JSON, and personal
recordings are ignored because they are reproducible or private runtime data.
Lesson checkpoint JSON is retained under `data/generated/` so expensive Codex
work can be reviewed and resumed. `.env` is ignored because it contains the
ElevenLabs secret.

Reference audio is cached on disk. Only `*.tmp` audio files are ignored by the
project rule; completed MP3 handling can therefore follow the repository's Git
LFS policy.
