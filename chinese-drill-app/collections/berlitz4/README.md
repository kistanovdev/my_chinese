# Berlitz 4 collection

This directory is the isolated build workspace for 18 Berlitz 4 lessons dated
2026-03-30 through 2026-06-08. Its current final deck contains 250 drills and
750 reference MP3s: three speakers for every card.

```text
data/sources.json       Source location, suffixes, and lesson inventory
data/voices.json        Three ElevenLabs speaker definitions
data/generated/         Checkpointed Codex output per lesson
build/                  Compiled deck and audio manifests (generated)
audio/                  Cached reference MP3s
dist/deck.json          Level-only app bundle (generated)
data/progress.json      Progress only when the isolated launcher is used
data/recordings/        Personal audio only when isolated mode records
```

Generate or resume the collection:

```bash
python3 scripts/run_pipeline.py \
  --collection collections/berlitz4 \
  --speaker-variants
```

Then refresh the normal unified app deck:

```bash
python3 scripts/merge_levels.py
python3 app.py --check
```

The unified app prefixes Berlitz 4 sentence IDs with `berlitz4-`, adds
`level: 4`, and maps audio URLs to `/audio/berlitz4/<filename>`. The MP3s stay
in this collection and are not copied into the main audio directory.

The optional legacy Level 4 launcher remains useful for inspecting only this
collection:

```bash
python3 app.py \
  --deck collections/berlitz4/dist/deck.json \
  --audio-directory collections/berlitz4/audio \
  --progress collections/berlitz4/data/progress.json
```

That isolated progress is separate from the unified app's
`data/progress.json`.
