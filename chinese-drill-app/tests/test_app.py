from __future__ import annotations

import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import (  # noqa: E402
    DECK_PATH,
    DrillApplication,
    default_progress,
    parse_range_header,
    resolve_audio_path,
    validate_progress,
)


class AppTests(unittest.TestCase):
    def test_default_progress_is_valid(self) -> None:
        value = validate_progress(default_progress(), {"sentence-one"})
        self.assertEqual(value["version"], 1)
        self.assertEqual(value["cards"], {})
        self.assertEqual(value["settings"]["session_size"], 10)
        self.assertEqual(value["settings"]["voice_mode"], "original")
        self.assertTrue(value["settings"]["record_after_sequence"])
        self.assertIsNotNone(value["updated_at"])

    def test_progress_rejects_unknown_sentence(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        value = default_progress()
        value["cards"]["unknown"] = {
            "seen": 1,
            "box": 1,
            "streak": 1,
            "last_rating": "good",
            "last_reviewed": now,
            "next_due": now,
            "ratings": {"again": 0, "hard": 0, "good": 1, "easy": 0},
        }
        with self.assertRaisesRegex(ValueError, "unknown sentence ID"):
            validate_progress(value, {"sentence-one"})

    def test_existing_progress_gets_original_voice_mode(self) -> None:
        value = default_progress()
        del value["settings"]["voice_mode"]
        del value["settings"]["record_after_sequence"]
        validated = validate_progress(value, {"sentence-one"})
        self.assertEqual(validated["settings"]["voice_mode"], "original")
        self.assertTrue(validated["settings"]["record_after_sequence"])

    def test_one_card_session_is_valid(self) -> None:
        value = default_progress()
        value["settings"]["session_size"] = 1
        validated = validate_progress(value, {"sentence-one"})
        self.assertEqual(validated["settings"]["session_size"], 1)

    def test_range_parser_supports_standard_and_suffix_ranges(self) -> None:
        self.assertEqual(parse_range_header("bytes=10-19", 100), (10, 19))
        self.assertEqual(parse_range_header("bytes=90-", 100), (90, 99))
        self.assertEqual(parse_range_header("bytes=-10", 100), (90, 99))
        self.assertIsNone(parse_range_header(None, 100))

    def test_range_parser_rejects_unsatisfiable_range(self) -> None:
        with self.assertRaises(ValueError):
            parse_range_header("bytes=100-110", 100)

    def test_audio_path_resolver_supports_collections_and_rejects_traversal(self) -> None:
        self.assertEqual(
            resolve_audio_path("/audio/example.mp3", PROJECT_ROOT / "audio"),
            PROJECT_ROOT / "audio" / "example.mp3",
        )
        self.assertEqual(
            resolve_audio_path("/audio/berlitz3/example.mp3", PROJECT_ROOT / "audio"),
            PROJECT_ROOT / "collections" / "berlitz3" / "audio" / "example.mp3",
        )
        with self.assertRaises(ValueError):
            resolve_audio_path("/audio/berlitz3/../example.mp3", PROJECT_ROOT / "audio")

    def test_progress_round_trip_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            progress_path = Path(temp_name) / "progress.json"
            application = DrillApplication(DECK_PATH, progress_path)
            sentence_id = application.deck["sentences"][0]["id"]
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            progress = default_progress()
            progress["cards"][sentence_id] = {
                "seen": 1,
                "box": 1,
                "streak": 1,
                "last_rating": "good",
                "last_reviewed": now,
                "next_due": now,
                "ratings": {"again": 0, "hard": 0, "good": 1, "easy": 0},
            }
            application.save_progress(progress)
            reloaded = DrillApplication(DECK_PATH, progress_path)
            self.assertEqual(reloaded.progress["cards"][sentence_id]["seen"], 1)

    def test_default_deck_combines_all_berlitz_levels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            application = DrillApplication(
                DECK_PATH, Path(temp_name) / "progress.json"
            )
        sentences = application.deck["sentences"]
        self.assertEqual(len(sentences), 696)
        self.assertEqual(
            Counter(sentence.get("level") for sentence in sentences),
            Counter({3: 244, 4: 250, 5: 202}),
        )
        self.assertTrue(
            all(len(sentence.get("audio_variants", [])) == 3 for sentence in sentences)
        )

    def test_recording_is_saved_listed_reloaded_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            temp_path = Path(temp_name)
            progress_path = temp_path / "progress.json"
            recordings_path = temp_path / "recordings"
            application = DrillApplication(
                DECK_PATH,
                progress_path,
                recordings_directory=recordings_path,
            )
            sentence_id = application.deck["sentences"][0]["id"]
            saved = application.save_recording(
                sentence_id,
                b"recorded-audio" * 20,
                "audio/webm;codecs=opus",
                2300,
            )
            self.assertEqual(saved["sentence_id"], sentence_id)
            self.assertEqual(saved["mime_type"], "audio/webm")
            self.assertEqual(application.list_recordings(sentence_id), [saved])
            recording_file, mime_type = application.recording_file(saved["id"])
            self.assertTrue(recording_file.is_file())
            self.assertEqual(mime_type, "audio/webm")

            reloaded = DrillApplication(
                DECK_PATH,
                progress_path,
                recordings_directory=recordings_path,
            )
            self.assertEqual(reloaded.list_recordings(sentence_id), [saved])
            self.assertTrue(reloaded.delete_recording(saved["id"]))
            self.assertFalse(recording_file.exists())
            self.assertEqual(reloaded.list_recordings(sentence_id), [])

    def test_recording_rejects_unknown_sentence_and_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            application = DrillApplication(
                DECK_PATH,
                Path(temp_name) / "progress.json",
                recordings_directory=Path(temp_name) / "recordings",
            )
            with self.assertRaisesRegex(ValueError, "Unknown sentence"):
                application.save_recording(
                    "not-in-deck", b"audio" * 40, "audio/webm", 1000
                )
            sentence_id = application.deck["sentences"][0]["id"]
            with self.assertRaisesRegex(ValueError, "Unsupported recording format"):
                application.save_recording(
                    sentence_id, b"audio" * 40, "text/plain", 1000
                )


if __name__ == "__main__":
    unittest.main()
