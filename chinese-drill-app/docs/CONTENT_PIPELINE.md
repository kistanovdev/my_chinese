# Content pipeline

## Guiding rule

The analyses are the authority for corrected Mandarin. The transcripts are
used to recover intent, personal details, timestamps, and error frequency.
Teacher explanations and advanced lesson vocabulary are not automatically
treated as learner-ready material.

## Stage 1: inventory

Discover each pair:

- `YYYY-MM-DD-02-transcription.txt`
- `YYYY-MM-DD-04-transcription-analysis.txt`

The initial inventory contains 15 pairs from 2026-07-08 through 2026-09-30.

## Stage 2: generate candidates with Codex

`scripts/generate_sentences.py` invokes `codex exec` non-interactively once per
lesson. A JSON Schema constrains each final response, and each completed lesson
is checkpointed under `data/generated/`.

Codex extracts candidates from these parts of each analysis:

- Explicit corrected forms after `Better:`, `Correct:`, or `→`
- Positive examples identified as already correct
- Model sentences in the drill sections
- Short useful phrases

Use the raw transcript only when a corrected analysis sentence needs personal
context or a timestamp.

## Stage 3: turn corrections into drills

For each recurring pattern, create a small family rather than dozens of nearly
identical sentences:

1. One sentence directly connected to the learner's life.
2. One variation that changes the time, place, person, or object.
3. Optionally, one question or negative form.

Example:

```text
我在苹果公司工作了五年了。
我在这里住了三年了。
你学中文学了多长时间了？
```

## Sentence selection rules

Keep a sentence when it:

- Practises a recurring structural problem.
- Is likely to be useful in real conversation.
- Expresses one main idea.
- Can normally be spoken in roughly two to five seconds.
- Uses mostly known vocabulary, with at most one important new item.
- Sounds natural to a native Mandarin speaker.

Usually reject a sentence when it:

- Merely demonstrates an obscure vocabulary item.
- Depends on political, technical, or cultural context unlikely to recur.
- Is a long teacher explanation.
- Contains uncertain transcript wording.
- Repeats an existing sentence without teaching a useful variation.

Target length is usually 5 to 18 Chinese characters, excluding punctuation.
Longer sentences are allowed when the pattern itself requires two clauses.

## Priority calculation

Start with a human-readable score from 1 to 5:

- 5: the same error appears in three or more lessons
- 4: repeated error or essential HSK 3 structure
- 3: useful personal phrase seen once
- 2: useful but less urgent variation
- 1: recognition-only or optional vocabulary

Known high-priority families from the current analyses include:

- `再 + verb + 一次/一遍`
- `在 + place + verb`
- `verb + 了 + duration + 了`
- `没 + verb + 过`
- `跟/给 + person + verb`
- `去 + place + 旅游/出差`
- `有 + noun + 要 + verb`
- Adjective predicates without an unnecessary `是`
- `如果……，就……` and `虽然……，但是……`
- Verb-object chunks such as `参加会议`, `签合同`, and `解决问题`

## Deduplication

Normalize punctuation and whitespace, then deduplicate exact sentences. At the
pattern level, retain no more than three close variations unless the pattern is
a top-priority recurring error.

## Review gates

A generated candidate should not be sent to the full TTS run until it passes
these checks. The Codex prompt performs an initial language review, the Python
scripts enforce the data contract, and `build/sentences.json` remains easy to
inspect before spending ElevenLabs credits:

- Chinese is grammatical and idiomatic.
- Meaning matches the intended scenario.
- Pinyin, if present, has correct tone marks and neutral tones.
- The TTS text contains only what should be spoken.
- Numbers and symbols are written in a form that will be pronounced correctly.
- Source lesson and focus pattern are recorded.
- Personal facts are not invented when the source is ambiguous.

## Compilation

`scripts/compile_deck.py` validates all 15 checkpoint files, creates stable IDs,
merges exact duplicate sentences, combines their sources and focus tags, and
writes `build/sentences.json`.

## Audio generation

`scripts/synthesize_audio.py` sends the compiled `tts_text` values to
ElevenLabs. Synthesis is incremental:

1. Compute a content hash from TTS text, model, voice, and settings.
2. Skip an entry when a matching audio file already exists.
3. Save generation metadata beside the deck.
4. Retry transient failures without duplicating successful requests.
5. Validate that every item has a non-empty playable audio file.

## App-data build

`scripts/build_app_data.py` combines the compiled deck with the audio manifest.
It fails on missing audio by default and writes `dist/deck.json`, the only
content contract the future practice app needs to understand.

## Data lifecycle

```text
transcripts + analyses
        ↓
candidate extraction
        ↓
data/generated/YYYY-MM-DD.json
        ↓ validation and deduplication
build/sentences.json
        ↓ ElevenLabs synthesis and caching
audio/*.mp3 + build/audio-manifest.json
        ↓ final validation
dist/deck.json
        ↓
practice web app
```
