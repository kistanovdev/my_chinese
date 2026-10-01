from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from build_app_data import build_bundle  # noqa: E402
from common import normalize_chinese, sentence_id  # noqa: E402
from compile_deck import merge_candidate  # noqa: E402
from synthesize_audio import audio_hash  # noqa: E402


class PipelineTests(unittest.TestCase):
    def test_normalization_ignores_spacing_and_punctuation(self) -> None:
        self.assertEqual(
            normalize_chinese("如果我不明白，我就问老师。"),
            normalize_chinese("如果我不明白 我就问老师"),
        )

    def test_sentence_id_is_stable(self) -> None:
        self.assertEqual(
            sentence_id("我再读一次。"), sentence_id("我再读一次")
        )

    def test_audio_hash_changes_with_voice(self) -> None:
        first = audio_hash("我再读一次。", "eleven_v4", "voice-a", "mp3", "zh")
        second = audio_hash("我再读一次。", "eleven_v4", "voice-b", "mp3", "zh")
        self.assertNotEqual(first, second)

    def test_merge_candidate_keeps_highest_priority_and_sources(self) -> None:
        existing = {
            "priority": 3,
            "focus": ["再 + verb"],
            "sources": [{"lesson": "one"}],
            "scenario": "Read again.",
            "english_hint": "Read it again.",
        }
        incoming = {
            "priority": 5,
            "focus": ["word order"],
            "sources": [{"lesson": "two"}],
            "scenario": "Say that you will read the sentence again.",
            "english_hint": "I will read it one more time.",
        }
        merge_candidate(existing, incoming)
        self.assertEqual(existing["priority"], 5)
        self.assertEqual(existing["focus"], ["再 + verb", "word order"])
        self.assertEqual(len(existing["sources"]), 2)

    def test_app_bundle_requires_real_audio_by_default(self) -> None:
        deck = {
            "sentences": [
                {
                    "id": "sentence-one",
                    "chinese": "我再读一次。",
                    "pinyin": "Wǒ zài dú yí cì.",
                    "english_hint": "I will read it again.",
                    "scenario": "Read again.",
                    "focus": ["再"],
                    "priority": 5,
                    "default_repetitions": 3,
                    "sources": [],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_name:
            with self.assertRaisesRegex(ValueError, "Missing audio"):
                build_bundle(deck, {"items": {}}, Path(temp_name), False)
            result = build_bundle(deck, {"items": {}}, Path(temp_name), True)
        self.assertEqual(result["missing_audio_count"], 1)
        self.assertIsNone(result["sentences"][0]["audio"])


if __name__ == "__main__":
    unittest.main()

