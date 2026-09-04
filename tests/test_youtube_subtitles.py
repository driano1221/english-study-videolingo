import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.youtube_subtitles import (
    _write_subtitle_pair,
    _translate_source_cues,
    align_automatic_tracks,
    group_automatic_source_for_translation,
    load_prepared_youtube_subtitles,
    normalize_automatic_cues,
    regroup_automatic_caption_pairs,
    subtitle_gap_stats,
    write_paired_subtitles,
)
from core.asr_quality import repeated_phrase_loops


SOURCE = """1
00:00:00,000 --> 00:00:01,500
First source line.

2
00:00:01,500 --> 00:00:04,000

3
00:00:04,000 --> 00:00:06,000
Second <i>source</i> line.
"""

TARGET = """1
00:00:00,100 --> 00:00:02,000
Primeira linha.

2
00:00:03,800 --> 00:00:06,200
Segunda linha.
"""


class YoutubeSubtitleTests(unittest.TestCase):
    def test_direct_caption_translation_uses_small_deterministic_batches(self):
        source = [
            {"start": index, "end": index + 1, "text": f"phrase {index}"}
            for index in range(25)
        ]
        calls = []

        def fake_translate(lines, *args, **kwargs):
            batch = lines.splitlines()
            calls.append((len(batch), kwargs))
            return "\n".join(f"PT {line}" for line in batch), lines

        with (
            mock.patch("core.translate_lines.translate_lines", side_effect=fake_translate),
            mock.patch(
                "core.youtube_subtitles.load_key",
                side_effect=lambda key: {
                    "translation.batch_chars": 6500,
                    "translation.batch_max_lines": 120,
                }[key],
            ),
        ):
            translated = _translate_source_cues(source)

        self.assertEqual([count for count, _ in calls], [24, 1])
        self.assertTrue(all(options["validation_retries_override"] == 0 for _, options in calls))
        self.assertTrue(all(options["temperature_override"] == 0.0 for _, options in calls))
        self.assertEqual(len(translated), 25)

    def test_translation_punctuation_restores_sentence_boundaries(self):
        source = [
            {"start": 0.0, "end": 1.5, "text": "we need room for"},
            {"start": 1.5, "end": 3.0, "text": "more then we continue"},
            {"start": 3.0, "end": 4.5, "text": "with the next idea"},
        ]
        target = [
            "precisamos de espaço para",
            "mais. Depois continuamos",
            "com a próxima ideia.",
        ]

        grouped_source, grouped_target = regroup_automatic_caption_pairs(source, target)

        self.assertEqual(len(grouped_source), 2)
        self.assertEqual(grouped_target[0], "precisamos de espaço para mais.")
        self.assertEqual(grouped_target[1], "Depois continuamos com a próxima ideia.")
        self.assertEqual(
            "".join(item["text"].replace(" ", "") for item in grouped_source),
            "".join(item["text"].replace(" ", "") for item in source),
        )
        self.assertAlmostEqual(grouped_source[0]["start"], 0.0)
        self.assertAlmostEqual(grouped_source[-1]["end"], 4.5)

    def test_source_fragments_are_grouped_before_translation(self):
        source = [
            {"start": 0.0, "end": 1.0, "text": "This is"},
            {"start": 1.0, "end": 2.0, "text": "one phrase"},
            {"start": 3.0, "end": 4.0, "text": "After a pause"},
        ]

        grouped = group_automatic_source_for_translation(source)

        self.assertEqual([item["text"] for item in grouped], ["This is one phrase", "After a pause"])

    def test_automatic_fragments_and_orphan_punctuation_are_grouped_locally(self):
        source = [
            {"start": 0.0, "end": 1.5, "text": "What happened to your life"},
            {"start": 1.5, "end": 2.5, "text": "when you said that?"},
            {"start": 2.5, "end": 4.0, "text": "I think it changed"},
            {"start": 4.0, "end": 5.0, "text": "everything."},
        ]
        target = [
            "O que aconteceu com sua vida",
            "?",
            "Acho que isso mudou",
            "tudo.",
        ]

        grouped_source, grouped_target = regroup_automatic_caption_pairs(source, target)

        self.assertEqual(len(grouped_source), 2)
        self.assertEqual(grouped_source[0]["text"], "What happened to your life when you said that?")
        self.assertEqual(grouped_target[0], "O que aconteceu com sua vida?")
        self.assertEqual(grouped_source[0]["start"], 0.0)
        self.assertEqual(grouped_source[0]["end"], 2.5)

    def test_automatic_regrouping_does_not_cross_a_real_pause(self):
        source = [
            {"start": 0.0, "end": 1.0, "text": "An unfinished"},
            {"start": 2.0, "end": 3.0, "text": "thought continues."},
        ]

        grouped_source, _ = regroup_automatic_caption_pairs(source, ["Uma frase", "continua."])

        self.assertEqual(len(grouped_source), 2)

    def test_valid_prepared_youtube_pair_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "log").mkdir()
            source = [
                {"start": 0.0, "end": 1.0, "text": "Hello."},
                {"start": 1.0, "end": 2.0, "text": "World."},
            ]
            target = ["Olá.", "Mundo."]
            _write_subtitle_pair(
                source,
                target,
                output,
                "youtube_automatic_subtitles",
            )

            cached = load_prepared_youtube_subtitles(output)

        self.assertIsNotNone(cached)
        self.assertEqual(cached["entries"], 2)

    def test_invalid_prepared_pair_is_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "log").mkdir()
            (output / "src.srt").write_text("broken", encoding="utf-8")
            (output / "trans.srt").write_text("broken", encoding="utf-8")
            (output / "log" / "subtitle_source.json").write_text(
                '{"source":"youtube_automatic_subtitles","entries":1}',
                encoding="utf-8",
            )

            cached = load_prepared_youtube_subtitles(output)

        self.assertIsNone(cached)

    def test_pairs_nonempty_tracks_by_order_and_source_timing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.srt"
            target = root / "target.srt"
            output = root / "output"
            source.write_text(SOURCE, encoding="utf-8")
            target.write_text(TARGET, encoding="utf-8")

            stats = write_paired_subtitles(source, target, output)
            generated_source = (output / "src.srt").read_text(encoding="utf-8")
            generated_target = (output / "trans.srt").read_text(encoding="utf-8")
            audit = json.loads((output / "log" / "subtitle_source.json").read_text(encoding="utf-8"))

        self.assertEqual(stats["entries"], 2)
        self.assertEqual(stats["internal_gap_seconds"], 2.5)
        self.assertNotIn("<i>", generated_source)
        self.assertIn("00:00:04,000 --> 00:00:06,000", generated_target)
        self.assertIn("Segunda linha.", generated_target)
        self.assertEqual(audit["source"], "youtube_manual_subtitles")

    def test_gap_stats_counts_only_positive_internal_gaps(self):
        cues = [
            {"start": 0.0, "end": 2.0, "text": "a"},
            {"start": 2.0, "end": 3.0, "text": "b"},
            {"start": 4.25, "end": 5.0, "text": "c"},
        ]
        stats = subtitle_gap_stats(cues)
        self.assertEqual(stats["internal_gap_count"], 1)
        self.assertEqual(stats["internal_gap_seconds"], 1.25)

    def test_automatic_caption_windows_are_made_non_overlapping(self):
        cues = [
            {"start": 0.0, "end": 4.2, "text": "first phrase"},
            {"start": 2.48, "end": 5.08, "text": "next phrase"},
            {"start": 4.2, "end": 7.76, "text": "third phrase"},
        ]
        normalized = normalize_automatic_cues(cues)
        self.assertEqual(normalized[0]["end"], 2.48)
        self.assertEqual(normalized[1]["end"], 4.2)
        self.assertEqual(subtitle_gap_stats(normalized)["overlap_count"], 0)

    def test_repeated_phrase_hallucinations_are_detected(self):
        words = "normal introduction the one who the one who the one who the one who the one who the one who ending".split()
        loops = repeated_phrase_loops(words)
        self.assertEqual(loops[0]["phrase"], "the one who")
        self.assertEqual(loops[0]["repeats"], 6)

    def test_automatic_tracks_with_different_grouping_align_by_time(self):
        source = [
            {"start": 0.0, "end": 1.0, "text": "first"},
            {"start": 1.0, "end": 2.0, "text": "second"},
            {"start": 2.0, "end": 3.0, "text": "third"},
        ]
        target = [
            {"start": 0.0, "end": 2.0, "text": "primeiro segundo"},
            {"start": 2.0, "end": 3.0, "text": "terceiro"},
        ]
        aligned_source, target_texts = align_automatic_tracks(source, target)
        self.assertEqual(len(aligned_source), 2)
        self.assertEqual(aligned_source[0]["text"], "first second")
        self.assertEqual(target_texts, ["primeiro segundo", "terceiro"])


if __name__ == "__main__":
    unittest.main()
