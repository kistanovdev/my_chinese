#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

python3 app.py \
  --deck collections/berlitz4/dist/deck.json \
  --audio-directory collections/berlitz4/audio \
  --progress collections/berlitz4/data/progress.json
