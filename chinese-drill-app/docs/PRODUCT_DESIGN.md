# Product design

This document describes the implemented product as of October 2026.

## Goal

Make correct Mandarin sentence structure automatic by repeatedly hearing and
saying short sentences drawn from the learner's own life and recurring Berlitz
lesson errors. The unit of practice is a complete, reusable sentence—not an
isolated vocabulary item.

The app is designed for a learner who has passed HSK 2 and is moving toward
HSK 3. Vocabulary and passive comprehension are stronger than spontaneous
sentence production, so the experience emphasizes retrieval, word order,
rhythm, and repeated speaking.

## Content

The runtime deck contains 696 drills:

- Berlitz 3: 244
- Berlitz 4: 250
- Berlitz 5: 202

High-value patterns include time/place order, durations, aspect markers,
complements, prepositional phrases, comparisons, conditionals, and common
verb-object chunks. Personal topics—work, family, travel, meetings, products,
money, housing, and Chinese study—are preferred over generic textbook prose.

## Session setup

The dashboard offers:

- Session size: 1, 5, 10, 15, 20, or 30 cards; default 10
- Repetitions: 2 or 3; default 3
- Playback speed: natural or 0.85x
- Speakers: original or varied
- Recording: prompt after the final play or disabled

Settings are part of `data/progress.json` and save immediately when changed.

## Card flow

1. The card shows an English scenario cue, focus tags, lesson date, and
   Berlitz level. The Mandarin answer is concealed.
2. The learner starts the reference sequence.
3. The app plays the sentence and provides a long speaking pause after each
   non-final round. Two or three rounds are used according to the session
   setting.
4. After the final round, simplified Chinese is revealed. Pinyin and English
   translation remain hidden.
5. When recording prompts are enabled, an optional microphone panel appears.
   Rating is already available; the learner can press `1`–`4` immediately.
6. If the learner records, rating is paused only during capture and save. The
   app then offers reference-versus-recording playback and restores rating.
7. The selected rating is saved, and the app advances automatically.

The recording panel deliberately does not create a required extra step. The
learner may record, press **Skip this time**, click a rating, or press a rating
number as soon as the final reference finishes.

## Text disclosure

Text supports listening rather than replacing it:

- Simplified Chinese begins concealed and is revealed after playback or with
  **Reveal sentence** / `R`.
- Pinyin begins hidden and independently toggles with **Show/Hide pinyin** or
  `P`.
- English translation begins hidden and independently toggles with
  **Show/Hide translation** or `T`.
- Showing or hiding pinyin never changes translation visibility, and vice
  versa.

## Speaker behavior

Every card has three cached voices:

- Mr. Chen: male, Beijing Mandarin, primary
- Chen: female, Taiwan Mandarin
- Anna Su: female, Taiwan Mandarin

Original mode uses the primary voice for every repetition. Varied mode shuffles
the available speakers for each card and rotates across them during the
sequence. Changing voice mode never changes the card's scheduling identity.

## Recording and comparison

Recording is implemented with the browser `MediaRecorder` API. It is always a
learner choice and never begins automatically.

The first attempt triggers browser microphone permission. While recording, the
interface shows an elapsed timer and stops automatically at 30 seconds. After
capture:

- The attempt is saved locally.
- **Reference** plays the most recently heard reference voice.
- **My recording** plays the captured attempt.
- **Record another** creates an additional historical attempt rather than
  replacing the previous one.
- Earlier attempts are listed newest first with their date, duration, Play,
  and Delete controls.

There is no automatic pronunciation score. Side-by-side listening is more
honest about tones, rhythm, and pronunciation than a transcription-only score.

## Queue construction

The app divides the deck into due, unseen, and future cards whenever the
dashboard or a session queue is built.

- Due cards are ordered by due timestamp, then by content priority.
- Unseen cards are Fisher–Yates shuffled at the start of every session. This
  removes the old Level 3-first bias caused by ID ordering and naturally mixes
  all course levels.
- A session takes due cards first and fills remaining slots from the shuffled
  unseen pool.
- If no due or unseen card is available, the app selects the earliest future
  cards for optional early practice.

## Scheduling

The scheduler uses six boxes with intervals of 1, 3, 7, 14, 30, and 60 days.

- Again: reset to box 0, schedule tomorrow, and append one retry to the current
  session
- Hard: keep at least box 1 and schedule tomorrow
- Good: advance one box and use that box's interval
- Easy: advance two boxes and use that box's interval

Each card records seen count, box, streak, last rating, last review time, next
due time, and cumulative counts for all four ratings. Session-level totals and
the last completed session are also saved.

## Local-first principles

- The server binds only to localhost by default.
- Reference audio is generated ahead of time; daily practice has no cloud
  dependency.
- The ElevenLabs API key is never sent to the browser.
- Progress and recording metadata use atomic JSON writes.
- Personal microphone files remain under `data/recordings/` and are ignored by
  Git.
- Recording failure never prevents rating or completing a card.

## Implemented acceptance criteria

- All 51 source lessons across Berlitz 3, 4, and 5 are represented.
- The unified deck has 696 unique IDs and no missing reference audio.
- Each card has three playable reference voices.
- Sessions work offline after the localhost server starts.
- One-card sessions support quick testing; ten cards remain the default.
- Unseen cards mix all three levels on every new session.
- Chinese, pinyin, and translation have independent disclosure behavior.
- Recording is optional and historical attempts survive restarts.
- Progress survives browser and server restarts.

## Possible future improvements

- A dashboard-wide recording-history browser
- Export/import for progress and recordings
- Optional waveform display
- Optional transcription as feedback, clearly separated from pronunciation
  assessment
- Packaging the standard-library server as a signed macOS application
