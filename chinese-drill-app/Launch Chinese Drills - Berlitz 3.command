#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

python3 app.py \
  --deck collections/berlitz3/dist/deck.json \
  --audio-directory collections/berlitz3/audio \
  --progress collections/berlitz3/data/progress.json
