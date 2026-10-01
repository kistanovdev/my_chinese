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

The product and content pipeline are designed, the Berlitz 5 source set is
inventoried, and a small pilot deck demonstrates the proposed sentence format.
No ElevenLabs requests have been made yet.

## Proposed MVP

- Local responsive web app, launched with one command.
- Audio-first cards with Chinese hidden initially.
- Two or three repetitions per sentence, configurable per session.
- Reveal controls for simplified Chinese, pinyin, and a short English hint.
- Keyboard controls: space to replay, enter to advance, and number keys to rate.
- Daily queue biased toward high-priority recurring errors.
- Cached MP3 audio so normal practice makes no API calls.
- Progress stored locally; no account or cloud service required.

## Project layout

```text
chinese-drill-app/
  README.md
  .env.example
  data/
    sources.json
    sentences.sample.json
  docs/
    PRODUCT_DESIGN.md
    CONTENT_PIPELINE.md
  audio/                 # Generated files; ignored by git
  scripts/               # Extraction and synthesis tools (next milestone)
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

## Planned commands

These commands describe the intended interface; the scripts will be added in
the implementation milestone.

```bash
# Build or refresh candidate sentences from the source files.
python3 scripts/build_deck.py

# Preview a few voice/model combinations before committing credits.
python3 scripts/preview_voices.py

# Generate only missing or changed audio.
python3 scripts/synthesize_audio.py

# Launch the local practice app.
python3 scripts/serve.py
```

See [PRODUCT_DESIGN.md](docs/PRODUCT_DESIGN.md) for the experience and
[CONTENT_PIPELINE.md](docs/CONTENT_PIPELINE.md) for extraction and quality
rules.

