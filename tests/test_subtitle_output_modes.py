import sys
import tempfile
import unittest
from pathlib import Path


VIDEO_LINGO_ROOT = Path(__file__).resolve().parents[1]
if str(VIDEO_LINGO_ROOT) not in sys.path:
    sys.path.insert(0, str(VIDEO_LINGO_ROOT))

from core._7_sub_into_vid import _ffmpeg_command, _write_bilingual_ass, normalize_subtitle_mode


class SubtitleOutputModeTests(unittest.TestCase):
    def command_filter(self, mode):
        command = _ffmpeg_command("input.mp4", 1920, 1080, "libx264", mode)
        return command[command.index("-vf") + 1]

    def test_bilingual_mode_burns_both_tracks(self):
        video_filter = self.command_filter("bilingual")
        self.assertIn("bilingual.ass", video_filter)
        self.assertNotIn("BorderStyle=4", video_filter)

    def test_portuguese_mode_burns_only_translation(self):
        video_filter = self.command_filter("portuguese")
        self.assertNotIn("src.srt", video_filter)
        self.assertIn("trans.srt", video_filter)

    def test_english_mode_burns_only_source(self):
        video_filter = self.command_filter("english")
        self.assertIn("src.srt", video_filter)
        self.assertNotIn("trans.srt", video_filter)

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_subtitle_mode("klingon")

    def test_bilingual_ass_stacks_equal_size_colored_lines_without_box(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source_path = folder / "src.srt"
            translation_path = folder / "trans.srt"
            source_path.write_text(
                "1\n00:00:01,000 --> 00:00:03,000\nEnglish line\n",
                encoding="utf-8",
            )
            translation_path.write_text(
                "1\n00:00:01,000 --> 00:00:03,000\nLinha em português\n",
                encoding="utf-8",
            )
            contents = []
            for scale in (1.0, 0.75):
                output = folder / f"bilingual-{scale}.ass"
                _write_bilingual_ass(
                    1280, 720, scale, output, source_path, translation_path
                )
                contents.append(output.read_text(encoding="utf-8-sig"))

        self.assertIn("Style: Bilingual,Arial,30,", contents[0])
        self.assertIn("Style: Bilingual,Arial,22,", contents[1])
        self.assertIn(r"{\c&H00B8F4FF&}Linha em português\N{\c&H00FFFFFF&}English line", contents[0])
        self.assertIn(",1,2,0,2,20,20,18,1", contents[0])


if __name__ == "__main__":
    unittest.main()
