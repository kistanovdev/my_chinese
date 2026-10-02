# Runtime architecture

The application deliberately avoids Flask, FastAPI, React, a database, and a
frontend build system. Daily use requires one Python process and a browser.

## Components

```text
Launch Chinese Drills.command
          ↓
       app.py ─────────────── data/progress.json
          │                  data/recordings/index.json
          │                  data/recordings/*.{webm,mp4,ogg,wav}
          │
          ├── web/index.html + styles.css + app.js
          ├── dist/deck.json
          └── reference MP3s in main and collection audio directories
```

`app.py` uses `ThreadingHTTPServer` and `BaseHTTPRequestHandler` from Python's
standard library. It validates the complete deck at startup before opening the
browser. The frontend is a single-page interface written in plain JavaScript.

## Startup

The macOS launcher changes to its own directory and executes:

```bash
python3 app.py
```

Defaults:

- Host: `127.0.0.1`
- Port: `8765`
- Deck: `dist/deck.json`
- Progress: `data/progress.json`
- Level 5 audio: `audio/`
- Recordings: a `recordings/` directory beside the selected progress file

Useful server flags:

```text
--host HOST
--port PORT
--no-browser
--check
--deck PATH
--progress PATH
--audio-directory PATH
--recordings-directory PATH
```

`--check` loads and validates the deck, progress (if present), recording index
(if present), and every audio reference, then exits without starting HTTP.

## HTTP interface

| Method | Path | Purpose |
| --- | --- | --- |
| GET/HEAD | `/`, `/index.html`, `/styles.css`, `/app.js` | Browser application |
| GET/HEAD | `/api/health` | Health and sentence count |
| GET/HEAD | `/api/deck` | Validated unified deck |
| GET/HEAD | `/api/progress` | Current progress/settings object |
| PUT | `/api/progress` | Validate and atomically save progress |
| GET | `/api/recordings?sentence_id=…` | List one card's attempts, newest first |
| POST | `/api/recordings?sentence_id=…` | Save raw browser-recorded audio |
| DELETE | `/api/recordings/<recording-id>` | Delete one indexed attempt |
| GET/HEAD | `/recordings/<recording-id>` | Stream a personal recording |
| GET/HEAD | `/audio/<path>` | Stream cached reference audio with ranges |

JSON API responses use `no-store`. Static interface files use `no-cache`.
Reference MP3s are immutable and receive long-lived cache headers. Both
reference audio and personal recordings support HTTP byte ranges so browser
seeking works.

## Deck validation and audio routing

At startup, `validate_deck()` requires:

- A nonempty sentence array
- Unique, nonempty sentence IDs
- A valid primary `/audio/…` path for every card
- A valid list of audio variants
- Existing files of at least 100 bytes for every referenced MP3

The unified deck uses three URL shapes:

```text
/audio/<filename>                    → audio/<filename> (Berlitz 5)
/audio/berlitz3/<filename>           → collections/berlitz3/audio/<filename>
/audio/berlitz4/<filename>           → collections/berlitz4/audio/<filename>
```

`resolve_audio_path()` accepts only those namespaces, flat `.mp3` filenames,
and no empty, `.` or `..` path components. This lets one app use all collection
audio without duplicating files or permitting arbitrary filesystem access.

## Progress model

Progress is a versioned JSON object:

```json
{
  "version": 1,
  "updated_at": "2026-10-02T12:00:00+00:00",
  "settings": {
    "session_size": 10,
    "repetitions": 3,
    "playback_speed": 1.0,
    "voice_mode": "original",
    "record_after_sequence": true
  },
  "stats": {
    "total_reviews": 0,
    "sessions_completed": 0,
    "last_session": null
  },
  "cards": {}
}
```

Every saved card record contains seen count, box, streak, last rating,
last-reviewed timestamp, next-due timestamp, and per-rating counters. The
server rejects unknown card IDs, invalid settings, malformed timestamps,
negative counters, and request bodies larger than 2 MB.

Older progress created before speaker variety or recording settings remains
valid: validation inserts `voice_mode: original` and
`record_after_sequence: true` when those fields are absent.

`atomic_write_json()` writes to a temporary file in the destination directory
and replaces the previous file only after the new JSON is complete.

## Session queue

`readySentences()` classifies every sentence using progress:

- `due`: reviewed and `next_due` is now or earlier
- `fresh`: no progress entry
- `future`: reviewed but not due

Due cards are sorted by timestamp and priority. `buildSessionQueue()` performs
a fresh Fisher–Yates shuffle of unseen cards, then selects due cards followed
by shuffled unseen cards up to the requested session size. Future cards are
used only when nothing is due or unseen.

Again-rated cards are appended once to the same in-memory queue with a
`retried` marker, preventing an infinite retry loop.

## Playback state machine

The frontend keeps application state in one `state` object. Important fields
include the deck, progress, current queue item, reference `Audio` element,
speaker order, repetition count, timers, rating readiness, and recording
session.

For each card:

1. `prepareCurrentCard()` resets prior playback/recording state and hides all
   answer layers.
2. `startSequence()` initializes repetition state.
3. `playSequenceRound()` selects the current voice and plays its MP3.
4. The audio `ended` event calls `finishRepetitionRound()`.
5. Non-final rounds wait for `max(4.5 seconds, audio duration × 1.35 + 2
   seconds)` before the next play.
6. The final round either reveals rating directly or enters the optional
   recording phase.

Original voice mode retains the primary variant. Varied mode shuffles the three
speaker variants per card and cycles through that order.

## Answer visibility

The simplified Chinese answer, pinyin, and English translation are separate UI
states:

- Chinese is controlled by the concealed answer block.
- Pinyin always resets hidden and toggles independently.
- English always resets hidden and toggles independently.

The recording phase reveals Chinese for comparison but does not automatically
show pinyin or translation.

## Browser recording flow

The frontend uses `navigator.mediaDevices.getUserMedia()` and
`MediaRecorder`. It requests echo cancellation, noise suppression, and
automatic gain control. Preferred formats are tried in this order:

1. `audio/webm;codecs=opus`
2. `audio/mp4`
3. `audio/ogg;codecs=opus`
4. `audio/webm`
5. Browser default as a fallback

The target bitrate is 64 kbps where the browser accepts that option. A timer
updates four times per second, and capture stops at 30 seconds.

Recording is optional at the state-machine level:

- `enterRecordingPhase()` immediately calls `setRatingReady()`, so clicking a
  rating or pressing `1`–`4` works before recording.
- `startRecording()` hides rating while capture is active.
- Stopping creates a local Blob URL immediately for comparison, then POSTs the
  Blob to the local server.
- Success replaces the temporary Blob URL with the persisted recording URL,
  adds the attempt to history, and restores rating.
- Failure keeps the temporary recording playable and restores rating; it does
  not block the card.
- Leaving a card cancels active capture, stops microphone tracks, clears
  timers, revokes temporary URLs, and ignores delayed permission/upload
  responses.

## Recording persistence

The server accepts a raw audio request body plus:

- Query: `sentence_id`
- Header: `Content-Type`
- Header: `X-Recording-Duration-Ms`

It enforces:

- Sentence ID must exist in the loaded deck
- MIME type must normalize to WebM, MP4, Ogg, or WAV
- Payload must be 128 bytes to 10 MB
- Duration must be 0 to 60 seconds (the UI stops at 30)
- Generated IDs and filenames must match a strict server-owned pattern

Files receive IDs such as:

```text
recording-20261002T120000Z-a1b2c3d4e5f6.webm
```

`data/recordings/index.json` stores ID, sentence ID, UTC creation time,
duration, normalized MIME type, byte size, and filename. The API adds an
`audio_url` when returning metadata. The server never trusts a client-supplied
filename.

Binary data is written to a temporary file, flushed and `fsync`ed, then moved
into place. The recording index is updated atomically. If index persistence
fails, the new binary file is removed. Deletion updates the index first and
then removes the binary.

## Security and privacy boundaries

- Default binding is loopback-only, not the LAN.
- Static and audio path resolution rejects traversal.
- Deck and progress IDs are checked against the loaded deck.
- Request bodies have explicit size limits.
- MIME types and recording IDs use allowlists/regular expressions.
- `.env` and personal recordings are excluded from Git.
- ElevenLabs credentials are used only by offline pipeline scripts.
- The daily app does not send reference or microphone audio to a cloud API.

## Testing

The Python suite covers progress validation/migration, range parsing, audio
path safety, merged-level counts, three-voice coverage, recording
save/list/reload/delete behavior, format rejection, stable IDs, deduplication,
and bundle/audio validation.

Run:

```bash
python3 -m unittest discover -s tests -v
python3 app.py --check
node --check web/app.js
```

The browser still needs one manual check for microphone permission and the
actual audio input device, because automated unit tests do not grant macOS
browser microphone access.
