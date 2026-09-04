import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, WORKSPACE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.desktop import (
    FINAL_OUTPUT_DIR,
    VideoLingoApp,
    build_output_filename,
    format_api_usage,
    read_api_usage_summary,
)


class ApiUsageDisplayTests(unittest.TestCase):
    def test_final_videos_have_a_stable_organized_folder(self):
        self.assertEqual(FINAL_OUTPUT_DIR, WORKSPACE_ROOT / "videos" / "finalizados")

    def test_output_filename_matches_selected_subtitle_mode(self):
        self.assertEqual(build_output_filename("lesson", "bilingual"), "lesson_bilingual.mp4")
        self.assertEqual(build_output_filename("lesson", "portuguese"), "lesson_pt-br.mp4")
        self.assertEqual(build_output_filename("lesson", "english"), "lesson_english.mp4")
        self.assertEqual(
            build_output_filename("lesson", "bilingual", "fast"),
            "lesson_bilingual_fast.mkv",
        )
        with self.assertRaises(ValueError):
            build_output_filename("lesson", "unknown")

    def test_reads_and_formats_api_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            log_dir = output / "gpt_log"
            log_dir.mkdir()
            (log_dir / "usage_summary.json").write_text(
                json.dumps(
                    {
                        "api_calls": 3,
                        "prompt_tokens": 10465,
                        "completion_tokens": 6753,
                        "reasoning_tokens": 0,
                        "estimated_cost_usd": 0.00335594,
                    }
                ),
                encoding="utf-8",
            )

            summary = read_api_usage_summary(output)
            formatted = format_api_usage(summary)

            self.assertEqual(summary["api_calls"], 3)
            self.assertIn("US$ 0,00335594", formatted)
            self.assertIn("Chamadas: 3", formatted)
            self.assertIn("Tokens: 17.218", formatted)

    def test_missing_usage_file_returns_zero_totals(self):
        with tempfile.TemporaryDirectory() as folder:
            summary = read_api_usage_summary(Path(folder))

        self.assertEqual(summary["api_calls"], 0)
        self.assertEqual(summary["estimated_cost_usd"], 0.0)
        self.assertIn("US$ 0,00000000", format_api_usage(summary))

    def test_completion_dialog_and_status_show_cost(self):
        class FakeButton:
            def config(self, **kwargs):
                self.state = kwargs.get("state")

        app = object.__new__(VideoLingoApp)
        app.progress = {}
        app.process_btn = FakeButton()
        app.open_folder_btn = FakeButton()
        statuses = []
        logs = []
        app.set_status = statuses.append
        app.log = logs.append
        summary = {
            "api_calls": 3,
            "prompt_tokens": 10465,
            "completion_tokens": 6753,
            "estimated_cost_usd": 0.00335594,
        }

        with patch("app.desktop.messagebox.showinfo") as showinfo:
            app._finish_success(r"C:\video_final.mp4", summary)

        self.assertIn("US$ 0,00335594", statuses[0])
        self.assertIn("US$ 0,00335594", logs[0])
        self.assertIn("US$ 0,00335594", showinfo.call_args.args[1])
        self.assertEqual(app.process_btn.state, "normal")
        self.assertEqual(app.open_folder_btn.state, "normal")


if __name__ == "__main__":
    unittest.main()
