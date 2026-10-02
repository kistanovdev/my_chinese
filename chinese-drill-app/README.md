# Chinese Drill App

A local-first Mandarin speaking app built from the learner's Berlitz 3, 4,
and 5 transcripts and lesson evaluations. It uses only Python's standard
library in the backend and plain HTML, CSS, and JavaScript in the browser.

## Current deck

The default app combines all three course levels:

| Level | Drills | Reference audio |
| --- | ---: | ---: |
| Berlitz 3 | 244 | 732 MP3s |
| Berlitz 4 | 250 | 750 MP3s |
| Berlitz 5 | 202 | 606 MP3s |
| **Total** | **696** | **2,088 MP3s** |

Each drill has three ElevenLabs voices: Mr. Chen in Beijing Mandarin, Chen in
Taiwan Mandarin, and Anna Su in Taiwan Mandarin. The lesson chip shows both the
source date and level, for example `Lesson 2026-04-20 · Berlitz 4`.

## Launch

On macOS, double-click `Launch Chinese Drills.command`, or run:

```bash
cd /Users/kistanov/github/my_chinese/chinese-drill-app
python3 app.py
```

The server binds to `127.0.0.1:8765` and opens the browser automatically.
Press `Ctrl-C` in the Terminal window to stop it. Practice itself makes no
external network requests because all reference audio is already cached.

## Practice flow

1. Choose 1, 5, 10, 15, 20, or 30 cards. The default is 10.
2. Choose two or three repetitions, playback speed, speaker behavior, and
   whether to show a recording prompt.
3. Start the audio sequence. A generous pause follows each non-final play.
4. After the final play, the Chinese sentence is revealed. Pinyin and English
   remain hidden until requested.
5. Optionally record your version and compare it with the reference.
6. Rate the card with Again, Hard, Good, or Easy.

Recording never blocks progress. As soon as the recording prompt appears, the
rating buttons and keys `1`–`4` are active. Starting a recording temporarily
disables rating while audio is being captured and saved, then enables it again.
The **Skip this time** button only closes the recording panel; it is not
required to continue.

Controls during practice:

- `Space`: play the sequence, or replay the reference when rating is ready
- `R`: reveal simplified Chinese
- `P`: show or hide pinyin
- `T`: show or hide the English translation
- `1`–`4`: Again, Hard, Good, or Easy

## Queue and scheduling

Due reviews come first, ordered by due date and then priority. Unseen cards are
reshuffled with Fisher–Yates every time a session starts, so Berlitz 3, 4, and
5 naturally mix instead of appearing in level order. When nothing is due or
new, the earliest future cards can be practised ahead of schedule.

The scheduler is a small Leitner-style system:

- Again: retry once later in the same session and schedule for tomorrow
- Hard: schedule for tomorrow
- Good: advance one box
- Easy: advance two boxes
- Box intervals: 1, 3, 7, 14, 30, and 60 days

Progress is written atomically after every rating.

## Recording and privacy

The browser uses `MediaRecorder` and asks for microphone permission on the
first attempt. Recordings are capped at 30 seconds in the interface. The local
server accepts WebM, MP4, Ogg, or WAV audio, validates the sentence ID, format,
duration, and size, and stores each attempt immediately.

```text
data/recordings/
  index.json
  recording-YYYYMMDDTHHMMSSZ-<random>.<format>
```

History is stored per sentence and displayed newest first. Every attempt can
be replayed or deleted. Nothing is uploaded to ElevenLabs or another service.
`data/recordings/` is ignored by Git because it contains personal audio; copy
that folder when making a personal backup.

## Local data

| Data | Location | Git behavior |
| --- | --- | --- |
| Spaced-repetition progress and settings | `data/progress.json` | visible to Git |
| Personal recordings and recording index | `data/recordings/` | ignored |
| Unified runtime deck | `dist/deck.json` | generated and ignored |
| Level 5 intermediate build files | `build/` | generated and ignored |
| Level 3/4 collection builds | `collections/*/{build,dist}/` | generated and ignored |
| Cached reference MP3s | `audio/`, `collections/*/audio/` | source MP3s retained; temporary files ignored |

The app uses atomic temporary-file replacement for both progress and the
recording index, so an interrupted write does not replace a good JSON file with
a partial one.

## Project layout

```text
chinese-drill-app/
  app.py                         # Local HTTP server, validation, progress, recordings
  Launch Chinese Drills.command  # macOS launcher for the unified app
  data/                          # Level 5 config, progress, generated batches
  audio/                         # Level 5 reference audio
  build/                         # Level 5 intermediate artifacts
  dist/deck.json                 # Unified runtime deck after merge
  collections/
    berlitz3/                    # Level 3 config, generated data, build, audio, deck
    berlitz4/                    # Level 4 config, generated data, build, audio, deck
  scripts/                       # Extraction, compilation, TTS, build, and merge stages
  prompts/                       # Codex sentence-generation prompt
  schemas/                       # Structured-output JSON schema
  web/                           # Framework-free browser interface
  tests/                         # Python regression tests
  docs/
    PRODUCT_DESIGN.md            # Learning and interaction design
    CONTENT_PIPELINE.md          # Transcript-to-audio pipeline
    ARCHITECTURE.md              # Runtime implementation details
```

## Content pipeline

Run pipeline commands from the project directory. `.env` supplies the private
ElevenLabs key and voice configuration; it must not be committed.

```bash
# Preview the Level 5 stages without running them.
python3 scripts/run_pipeline.py --dry-run

# Build or resume Level 3, including all configured speakers.
python3 scripts/run_pipeline.py \
  --collection collections/berlitz3 \
  --speaker-variants

# Build or resume Level 4, including all configured speakers.
python3 scripts/run_pipeline.py \
  --collection collections/berlitz4 \
  --speaker-variants

# Build or resume Level 5.
python3 scripts/run_pipeline.py --speaker-variants

# Recreate the single Level 3 + 4 + 5 runtime deck.
python3 scripts/merge_levels.py
```

Useful pipeline controls include `--skip-codex`, `--skip-audio`,
`--force-sentences`, `--force-audio`, `--lesson YYYY-MM-DD`, and
`--audio-limit N`. Generation is checkpointed, and audio is content-addressed,
so successful work is reused on the next run.

See [CONTENT_PIPELINE.md](docs/CONTENT_PIPELINE.md) for the full data flow and
rebuild rules.

## Validation and tests

```bash
# Validate the unified deck and every referenced audio file.
python3 app.py --check

# Run the Python regression suite.
python3 -m unittest discover -s tests -v

# Check browser JavaScript syntax.
node --check web/app.js
```

The pipeline and app require Python 3.10 or newer. Codex CLI authentication and
an ElevenLabs API key are only required when generating new content or audio,
not for daily practice.

For implementation details, see [ARCHITECTURE.md](docs/ARCHITECTURE.md). For
the learning and interaction decisions, see
[PRODUCT_DESIGN.md](docs/PRODUCT_DESIGN.md).
