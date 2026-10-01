# Product design

## Product goal

Make correct Mandarin sentence structure automatic by repeatedly hearing and
saying short sentences drawn from the learner's own life and recurring lesson
errors.

This is not a general flashcard program and not another vocabulary list. The
unit of learning is a complete, reusable sentence pattern.

## Learner profile reflected in the design

- HSK 2 passed; working toward HSK 3.
- Passive understanding and vocabulary are ahead of spontaneous production.
- The largest recurring issue is assembling complete sentences quickly.
- High-value targets include time/place order, durations, aspect markers,
  complements, prepositional phrases, and common verb-object chunks.
- Personal topics such as work, family, travel, meetings, products, and Chinese
  study are more memorable than generic textbook examples.

## Core session

Each session contains about 10 to 20 sentences and should take 5 to 10 minutes.

1. The app shows a simple scenario cue and plays the Mandarin sentence.
2. The learner repeats it aloud.
3. The app waits, then plays the same sentence again.
4. After two or three rounds, the learner can reveal Chinese, pinyin, or an
   English hint.
5. The learner rates the sentence: Again, Hard, Good, or Easy.
6. The app advances automatically.

The default should be listening first. Text is a support, not the main event.

## Practice modes

### Repeat

Hear and repeat each sentence three times. This is the default and the MVP.

### Recall

Show a short scenario or English intent first. The learner says the Mandarin,
then reveals and hears the reference sentence.

### Contrast

Pair a recurring wrong pattern with two or three correct examples. The wrong
sentence is shown visually for explanation but is never synthesized.

Shadowing, microphone recording, and automatic pronunciation scoring are
possible later features. They are intentionally excluded from the first
version because they would complicate a habit that should feel nearly
frictionless.

## Card display

Default state:

- Topic or scenario cue
- Large play/pause control
- Repetition progress, such as `1 / 3`
- Reveal buttons

Revealed state:

- Simplified Chinese in large type
- Optional pinyin
- Optional short English meaning
- One concise grammar note, only when useful
- Source lesson date

## Scheduling

The MVP uses a small Leitner-style schedule rather than a complex algorithm:

- Again: later in the same session and tomorrow
- Hard: tomorrow
- Good: in three days
- Easy: in seven days

New sentences are capped per day. High-priority sentences and patterns that
occurred in multiple lessons enter the queue first.

## Audio design

Audio is generated ahead of time and stored under `audio/`. The browser never
receives the ElevenLabs API key.

Initial quality-first configuration:

- Model: `eleven_v4`
- Voice: a native Mainland Mandarin voice selected by listening test
- Output: `mp3_44100_128`
- Language hint: Chinese where supported by the endpoint
- Playback speed: normal by default, with optional 0.85x in the browser

Before full generation, the same 8 to 10 representative sentences should be
rendered with several native Mandarin voices. The sample must include `了`,
`过`, third-tone sequences, numbers, names, and a question. Choose the voice
for clear standard pronunciation and stable pacing, not dramatic expression.

Each audio filename is derived from a hash of the sentence, voice, model, and
settings. Changed content gets a new file; unchanged content reuses the cache.

## Technical shape

The first version is intentionally small:

- Python scripts for extraction, validation, and ElevenLabs generation
- Static HTML/CSS/JavaScript practice interface
- A local JSON progress file saved atomically after every rating
- Local Python standard-library HTTP server and automatic browser launch
- JSON as the reviewed deck format

This avoids a database, web framework, and frontend build system while leaving
a clean path to a small PyInstaller binary later. The first launcher can simply
be `python3 app.py`; it will start localhost, open the browser, and save progress
through a tiny local JSON endpoint.

## MVP acceptance criteria

- All 15 Berlitz 5 lesson pairs are represented in the reviewed deck.
- Every audio sentence is grammatical, natural, short, and traceable to a
  source lesson.
- No known incorrect learner sentence is synthesized.
- The app can complete a 10-sentence session without network access.
- Every sentence can be repeated two or three times without touching the
  mouse.
- Progress survives closing and reopening the browser.

## Decisions deferred until implementation

- Final Mandarin voice
- Two versus three repetitions as the global default (three is proposed)
- Whether pinyin is available immediately or only after the first attempt
- Whether progress should eventually sync across devices
