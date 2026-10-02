# Berlitz 4 collection

This collection is isolated from the main Berlitz 5 deck. It uses the shared
pipeline and web app code while keeping its generated JSON, audio, final deck,
and progress in this directory.

Generate or resume everything with three speakers:

```bash
python3 scripts/run_pipeline.py \
  --collection collections/berlitz4 \
  --speaker-variants
```

Launch this collection on localhost:

```bash
python3 app.py \
  --deck collections/berlitz4/dist/deck.json \
  --audio-directory collections/berlitz4/audio \
  --progress collections/berlitz4/data/progress.json
```
