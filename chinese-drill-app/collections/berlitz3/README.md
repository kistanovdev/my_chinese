# Berlitz 3 collection

This collection is isolated from the Berlitz 4 and Berlitz 5 decks. It uses
the shared pipeline and app code while keeping generated content, audio, final
deck, and progress under this directory.

Generate or resume everything with all three speakers:

```bash
python3 scripts/run_pipeline.py \
  --collection collections/berlitz3 \
  --speaker-variants
```

Launch this collection:

```bash
python3 app.py \
  --deck collections/berlitz3/dist/deck.json \
  --audio-directory collections/berlitz3/audio \
  --progress collections/berlitz3/data/progress.json
```
