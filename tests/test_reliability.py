import json
import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
VIDEOLINGO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(VIDEOLINGO_ROOT))
os.chdir(VIDEOLINGO_ROOT)

from app.pipeline_cache import JobCache, build_job_id, config_fingerprint, normalize_source
stage7_module = importlib.import_module("core._7_sub_into_vid")
stage1_module = importlib.import_module("core._1_ytdlp")
from core._7_sub_into_vid import probe_video
run_metrics_module = importlib.import_module("core.run_metrics")
from core.run_metrics import RunMetrics, subtitle_coverage
from core.asr_backend.runtime_utils import (
    hotwords_from_metadata,
    run_batch_fallback,
    speech_gap_candidates,
)
asr_stage_module = importlib.import_module("core._2_asr")
ask_gpt_module = importlib.import_module("core.utils.ask_gpt")
config_utils_module = importlib.import_module("core.utils.config_utils")
from core.utils.ask_gpt import _estimate_cost, _is_deepseek_peak, _is_retryable, _usage_dict
from core.utils.decorator import check_file_exists
from core.clean_subtitles import clean_text_lines, clean_word_df
from core.local_text import normalized_content, split_for_subtitle_pair, weighted_length

translation_module = importlib.import_module("core.translate_lines")
translate_stage_module = importlib.import_module("core._4_2_translate")
spacy_model_module = importlib.import_module("core.spacy_utils.load_nlp_model")
split_meaning_module = importlib.import_module("core._3_2_split_meaning")


class PipelineCacheTests(unittest.TestCase):
    def test_inference_profiles_have_separate_intermediate_caches(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.yaml"
            config.write_text("pipeline_cache_version: 10\n", encoding="utf-8")
            free = build_job_id("https://youtu.be/abc", "1080", "pt", config, "free")
            robust = build_job_id("https://youtu.be/abc", "1080", "pt", config, "robust")
        self.assertNotEqual(free, robust)

    def test_youtube_identity_ignores_playlist_parameters(self):
        first = normalize_source("https://www.youtube.com/watch?v=abc123&list=WL&index=20")
        second = normalize_source("https://youtu.be/abc123?t=10")
        self.assertEqual(first, "youtube:abc123")
        self.assertEqual(first, second)

    def test_api_secret_does_not_change_cache_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.yaml"
            config.write_text("api:\n  key: first-secret\n  model: deepseek-v4-flash\n", encoding="utf-8")
            first = config_fingerprint(config)
            first_id = build_job_id("https://youtu.be/abc", "1080", "Português brasileiro", config)
            config.write_text("api:\n  key: different-secret\n  model: deepseek-v4-flash\n", encoding="utf-8")
            self.assertEqual(first, config_fingerprint(config))
            self.assertEqual(
                first_id,
                build_job_id("https://youtu.be/abc", "1080", "Português brasileiro", config),
            )

    def test_switching_jobs_restores_intermediate_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            active = root / "output"
            cache = JobCache(active, root / "cache")

            self.assertFalse(
                cache.prepare("job-a", url="https://youtu.be/a", resolution="1080", target_language="pt")
            )
            (active / "log").mkdir(parents=True)
            (active / "log" / "translation.xlsx").write_bytes(b"translated-a")
            cache.save_active()

            self.assertFalse(
                cache.prepare("job-b", url="https://youtu.be/b", resolution="720", target_language="pt")
            )
            self.assertFalse((active / "log" / "translation.xlsx").exists())
            (active / "other.txt").write_text("job-b", encoding="utf-8")

            self.assertTrue(
                cache.prepare("job-a", url="https://youtu.be/a", resolution="1080", target_language="pt")
            )
            self.assertEqual((active / "log" / "translation.xlsx").read_bytes(), b"translated-a")
            self.assertFalse((active / "other.txt").exists())
            self.assertEqual(cache.active_metadata()["job_id"], "job-a")

    def test_raw_media_is_stored_once_and_relinked_between_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            active = root / "output"
            cache = JobCache(active, root / "cache")
            cache.prepare("job-a", url="https://youtu.be/shared", resolution="1080", target_language="pt")
            video = active / "lesson.mp4"
            video.write_bytes(b"video-data")
            (active / "input_manifest.json").write_text(
                json.dumps({"path": "output/lesson.mp4", "type": "video"}), encoding="utf-8"
            )
            (active / "output_sub.mp4").write_bytes(b"derived-render")
            snapshot = cache.save_active()

            self.assertFalse((snapshot / "lesson.mp4").exists())
            self.assertFalse((snapshot / "output_sub.mp4").exists())
            canonical = next((root / "cache" / "media").rglob("lesson.mp4"))
            self.assertEqual(canonical.read_bytes(), b"video-data")
            self.assertTrue(os.path.samefile(video, canonical))

            cache.prepare("job-b", url="https://youtu.be/shared", resolution="1080", target_language="pt")
            self.assertEqual((active / "lesson.mp4").read_bytes(), b"video-data")
            self.assertEqual(
                json.loads((active / "input_manifest.json").read_text(encoding="utf-8"))["path"],
                "output/lesson.mp4",
            )

    def test_disk_guard_rejects_resolution_that_cannot_fit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = JobCache(root / "output", root / "cache")
            usage = SimpleNamespace(total=10 * 1024**3, used=9 * 1024**3, free=1 * 1024**3)
            with mock.patch.object(shutil, "disk_usage", return_value=usage):
                with self.assertRaisesRegex(RuntimeError, "Espaço insuficiente"):
                    cache.ensure_free_space("1080")


class ReliabilityTests(unittest.TestCase):
    def test_int8_batch_probe_falls_back_4_2_1(self):
        attempts = []

        def transcribe(batch):
            attempts.append(batch)
            if batch > 1:
                raise RuntimeError("CUDA out of memory")
            return {"segments": []}

        result, selected = run_batch_fallback(transcribe)
        self.assertEqual(attempts, [4, 2, 1])
        self.assertEqual(selected, 1)
        self.assertEqual(result, {"segments": []})

    def test_hotwords_use_title_and_description_names(self):
        value = hotwords_from_metadata(
            {
                "title": "Why Kanye West Might Be A Philosophy Genius",
                "description": "Kanye West discusses Friedrich Nietzsche with Lex Fridman.",
            }
        )
        self.assertIn("Kanye West", value)
        self.assertIn("Friedrich Nietzsche", value)
        self.assertIn("Lex Fridman", value)

    def test_energy_vad_selects_speech_gap_not_silence(self):
        import numpy as np

        sample_rate = 1000
        audio = np.zeros(5000, dtype=np.float32)
        audio[2000:3000] = 0.08
        segments = [{"start": 0, "end": 2}, {"start": 3, "end": 5}]
        settings = {
            "repair_max_gaps": 4,
            "repair_min_gap": 0.5,
            "repair_max_gap": 2,
        }
        gaps = speech_gap_candidates(segments, audio, sample_rate, settings)
        self.assertEqual(len(gaps), 1)
        self.assertEqual((gaps[0]["start"], gaps[0]["end"]), (2.0, 3.0))

    def test_local_asr_uses_one_session_for_all_audio_segments(self):
        calls = []

        class FakeSession:
            def __init__(self, raw, vocal, profile):
                calls.append(("init", raw, vocal, profile))

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                calls.append(("close",))

            def transcribe_range(self, start, end):
                calls.append(("range", start, end))
                return {"segments": [{"start": start, "end": end, "words": []}]}

            def repair_gaps(self, result):
                calls.append(("repair", len(result["segments"])))
                return result

        fake_module = SimpleNamespace(WhisperSession=FakeSession)
        with (
            mock.patch.dict(sys.modules, {"core.asr_backend.whisperX_local": fake_module}),
            mock.patch.object(asr_stage_module, "find_media_file", return_value=("video.mp4", "video")),
            mock.patch.object(asr_stage_module, "convert_video_to_audio"),
            mock.patch.object(asr_stage_module, "split_audio", return_value=[(0, 10), (10, 20)]),
            mock.patch.object(asr_stage_module, "load_key", side_effect=lambda key: {
                "demucs": False, "whisper.runtime": "local"
            }[key]),
            mock.patch.object(asr_stage_module, "process_transcription", return_value=SimpleNamespace()),
            mock.patch.object(asr_stage_module, "save_results"),
        ):
            asr_stage_module.transcribe.__wrapped__("robust")

        self.assertEqual(sum(item[0] == "init" for item in calls), 1)
        self.assertEqual([item for item in calls if item[0] == "range"], [
            ("range", 0, 10), ("range", 10, 20)
        ])
        self.assertIn(("repair", 2), calls)

    def test_encoder_fallback_order_is_nvenc_qsv_then_cpu(self):
        attempts = []

        def fake_encode(_command, encoder, output_path=stage7_module.OUTPUT_VIDEO):
            attempts.append(encoder)
            if encoder == "h264_nvenc":
                raise RuntimeError("driver mismatch")
            return {"format": {"duration": "10"}, "validated_size": 2048, "encoder_used": encoder}

        with (
            mock.patch.object(stage1_module, "is_audio_only_input", return_value=False),
            mock.patch.object(stage7_module, "find_video_files", return_value="input.mp4"),
            mock.patch.object(stage7_module, "_video_dimensions", return_value=(1280, 720)),
            mock.patch.object(stage7_module, "load_key", return_value=True),
            mock.patch.object(stage7_module, "check_encoder_available", return_value=True),
            mock.patch.object(stage7_module, "_encode_video", side_effect=fake_encode),
            mock.patch.object(stage7_module.os.path, "isfile", return_value=True),
        ):
            result = stage7_module.merge_subtitles_to_video("bilingual", "burned")

        self.assertEqual(attempts, ["h264_nvenc", "h264_qsv"])
        self.assertEqual(result["encoder_used"], "h264_qsv")

    def test_fast_mode_stream_copies_media_and_embeds_subtitle(self):
        command = stage7_module._fast_ffmpeg_command("lesson.mp4", "english")
        self.assertIn("copy", command)
        self.assertIn("output/src.srt", command)
        self.assertIn("language=eng", command)
        self.assertEqual(command[-1], "output/output_sub.mkv")

    def test_subtitle_coverage_merges_overlapping_intervals(self):
        with tempfile.TemporaryDirectory() as temp:
            srt = Path(temp) / "lesson.srt"
            srt.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nHi\n\n"
                "2\n00:00:01,500 --> 00:00:03,000\nthere\n\n",
                encoding="utf-8",
            )
            result = subtitle_coverage(srt, 10)
        self.assertEqual(result["cue_count"], 2)
        self.assertEqual(result["timeline_covered_seconds"], 3.0)
        self.assertEqual(result["timeline_coverage_ratio"], 0.3)

    def test_run_metrics_persists_stage_and_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "run_metrics.json"
            with (
                mock.patch.object(run_metrics_module, "_process_ram_mib", return_value=123.0),
                mock.patch.object(run_metrics_module, "_nvidia_vram_mib", return_value=456.0),
            ):
                with RunMetrics(destination, sample_interval=0.01) as metrics:
                    with metrics.stage("test_stage"):
                        pass
                    metrics.record(encoder="h264_qsv", asr_rtf=0.42)
            payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["encoder"], "h264_qsv")
        self.assertEqual(payload["asr_rtf"], 0.42)
        self.assertEqual(payload["resources"]["peak_nvidia_vram_mib"], 456.0)
        self.assertIn("elapsed_seconds", payload["stages"]["test_stage"])

    def test_deepseek_peak_windows_are_weekdays_only(self):
        from datetime import datetime, timezone

        self.assertTrue(_is_deepseek_peak(datetime(2026, 9, 3, 2, tzinfo=timezone.utc)))
        self.assertFalse(_is_deepseek_peak(datetime(2026, 9, 3, 5, tzinfo=timezone.utc)))
        self.assertFalse(_is_deepseek_peak(datetime(2026, 9, 6, 2, tzinfo=timezone.utc)))

    def test_legacy_api_key_is_migrated_out_of_yaml(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.yaml"
            config.write_text("api:\n  key: 'legacy-secret'\n", encoding="utf-8")
            with (
                mock.patch.object(config_utils_module, "CONFIG_PATH", str(config)),
                mock.patch.object(config_utils_module, "_external_api_key", return_value=""),
                mock.patch.object(config_utils_module, "_write_user_api_key") as save,
            ):
                self.assertTrue(config_utils_module.migrate_api_key_from_config())
            save.assert_called_once_with("legacy-secret")
            self.assertNotIn("legacy-secret", config.read_text(encoding="utf-8"))

    def test_zero_byte_stage_artifact_is_not_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "stage.xlsx"
            marker.write_bytes(b"")
            calls = []

            @check_file_exists(str(marker))
            def stage():
                calls.append("called")

            stage()
            self.assertEqual(calls, ["called"])

    def test_nonempty_stage_artifact_is_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "stage.xlsx"
            marker.write_bytes(b"valid")
            calls = []

            @check_file_exists(str(marker))
            def stage():
                calls.append("called")

            stage()
            self.assertEqual(calls, [])

    def test_probe_rejects_zero_byte_video(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "broken.mp4"
            video.write_bytes(b"")
            with self.assertRaisesRegex(RuntimeError, "invalid"):
                probe_video(str(video))

    def test_probe_rejects_video_without_audio(self):
        metadata = {
            "format": {"duration": "2.0", "size": "2048"},
            "streams": [{"codec_type": "video", "codec_name": "h264"}],
        }
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "silent.mp4"
            video.write_bytes(b"x" * 2048)
            fake_probe = SimpleNamespace(returncode=0, stdout=json.dumps(metadata), stderr="")
            with mock.patch.object(stage7_module, "_run", return_value=fake_probe):
                with self.assertRaisesRegex(RuntimeError, "audio"):
                    probe_video(str(video))

    def test_retry_policy_only_retries_transient_statuses(self):
        transient = RuntimeError("rate limited")
        transient.status_code = 429
        permanent = RuntimeError("bad request")
        permanent.status_code = 400
        self.assertTrue(_is_retryable(transient))
        self.assertFalse(_is_retryable(permanent))

    def test_normal_ytdlp_load_does_not_run_pip_upgrade(self):
        fake_class = type("FakeYoutubeDL", (), {})
        fake_module = SimpleNamespace(YoutubeDL=fake_class)
        with (
            mock.patch.dict(sys.modules, {"yt_dlp": fake_module}),
            mock.patch.object(stage1_module.subprocess, "check_call") as upgrade,
        ):
            self.assertIs(stage1_module.get_ytdlp(), fake_class)
        upgrade.assert_not_called()

    def test_ytdlp_uses_installed_node_runtime(self):
        with mock.patch.object(
            stage1_module.shutil,
            "which",
            side_effect=lambda name: r"C:\Program Files\nodejs\node.exe" if name == "node" else None,
        ):
            self.assertEqual(
                stage1_module.get_js_runtimes(),
                {"node": {"path": r"C:\Program Files\nodejs\node.exe"}},
            )

    def test_ytdlp_retries_and_resumes_transient_download_failures(self):
        captured = {}

        class FakeYoutubeDL:
            def __init__(self, options):
                captured.update(options)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def download(self, _urls):
                return 0

        with tempfile.TemporaryDirectory() as temp:
            media = Path(temp) / "video.mp4"
            media.write_bytes(b"valid-video-placeholder")
            with (
                mock.patch.object(stage1_module, "get_ytdlp", return_value=FakeYoutubeDL),
                mock.patch.object(stage1_module, "get_js_runtimes", return_value={}),
                mock.patch.object(stage1_module, "load_key", side_effect=lambda key: {
                    "youtube.cookies_path": "",
                    "allowed_video_formats": ["mp4"],
                }[key]),
            ):
                stage1_module.download_video_ytdlp("https://youtu.be/example", save_path=temp)

        self.assertTrue(captured["continuedl"])
        self.assertGreaterEqual(captured["retries"], 10)
        self.assertGreaterEqual(captured["fragment_retries"], 10)
        self.assertGreaterEqual(captured["extractor_retries"], 5)
        self.assertGreaterEqual(captured["socket_timeout"], 30)

    def test_usage_and_cost_include_reasoning_and_cache_breakdown(self):
        usage_object = SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            prompt_cache_hit_tokens=800,
            prompt_cache_miss_tokens=200,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=300),
        )
        usage = _usage_dict(usage_object)
        self.assertEqual(usage["reasoning_tokens"], 300)
        cost = _estimate_cost(
            usage,
            {"cache_hit": 0.0028, "cache_miss": 0.14, "output": 0.28},
        )
        expected = (800 * 0.0028 + 200 * 0.14 + 500 * 0.28) / 1_000_000
        self.assertAlmostEqual(cost, expected)

    def test_deepseek_request_disables_thinking_and_enforces_json_limits(self):
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
                    usage=SimpleNamespace(
                        prompt_tokens=10,
                        completion_tokens=4,
                        total_tokens=14,
                        prompt_cache_hit_tokens=0,
                        prompt_cache_miss_tokens=10,
                        completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
                    ),
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=FakeCompletions())

        config = {
            "api.key": "test-only",
            "api.model": "deepseek-v4-flash",
            "api.base_url": "https://api.deepseek.com",
            "api.llm_support_json": True,
            "api.thinking": False,
            "api.temperature": 0.2,
            "api.timeout_seconds": 30,
            "api.max_output_tokens": 321,
            "api.max_retries": 0,
            "api.validation_retries": 0,
            "api.max_cost_usd": 1.0,
            "api.cached_input_cost_per_million": 0.0028,
            "api.input_cost_per_million": 0.14,
            "api.output_cost_per_million": 0.28,
        }

        with tempfile.TemporaryDirectory() as temp:
            log_dir = Path(temp) / "gpt_log"
            with (
                mock.patch.object(ask_gpt_module, "OpenAI", FakeOpenAI),
                mock.patch.object(ask_gpt_module, "load_key", side_effect=lambda key: config[key]),
                mock.patch.object(ask_gpt_module, "GPT_LOG_FOLDER", str(log_dir)),
                mock.patch.object(ask_gpt_module, "USAGE_LOG_FILE", str(log_dir / "usage.jsonl")),
                mock.patch.object(ask_gpt_module, "USAGE_SUMMARY_FILE", str(log_dir / "usage_summary.json")),
            ):
                result = ask_gpt_module.ask_gpt("return JSON", resp_type="json", use_cache=False)

            summary = json.loads((log_dir / "usage_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(captured["response_format"], {"type": "json_object"})
        self.assertEqual(captured["max_tokens"], 321)
        self.assertEqual(captured["timeout"], 30)
        self.assertEqual(summary["api_calls"], 1)
        self.assertEqual(summary["prompt_tokens"], 10)


class LocalOptimizationTests(unittest.TestCase):
    def test_local_alignment_preserves_content_and_limits(self):
        source = "This is a long sentence, with a semantic pause, and useful context."
        target = "Esta é uma frase longa, com uma pausa semântica e contexto útil."
        source_parts, target_parts = split_for_subtitle_pair(source, target, 40, 1.2)
        self.assertEqual(normalized_content("".join(source_parts)), normalized_content(source))
        self.assertEqual(normalized_content("".join(target_parts)), normalized_content(target))
        self.assertEqual(len(source_parts), len(target_parts))
        self.assertLessEqual(max(map(weighted_length, source_parts)), 40)
        self.assertLessEqual(max(map(weighted_length, target_parts)) * 1.2, 40)

    def test_long_source_is_split_before_translation(self):
        class Token:
            is_space = False

        def lightweight_nlp(text):
            return [Token() for _ in text.split()]

        source = "This sentence is deliberately long, so translation receives semantic parts."
        parts = split_meaning_module.split_sentence_local(
            source, max_length=100, nlp=lightweight_nlp, max_chars=38
        )
        self.assertGreater(len(parts), 1)
        self.assertEqual(normalized_content("".join(parts)), normalized_content(source))
        self.assertLessEqual(max(map(weighted_length, parts)), 38)

    def test_deduplicator_keeps_legitimate_double_and_removes_third(self):
        frame = __import__("pandas").DataFrame(
            {
                "text": ["very", "very", "very", "good"],
                "start": [0.0, 0.2, 0.4, 0.6],
                "end": [0.2, 0.4, 0.6, 0.8],
            }
        )
        cleaned = clean_word_df(frame)
        self.assertEqual(cleaned["text"].tolist(), ["very", "very", "good"])
        self.assertEqual(cleaned.loc[1, "end"], 0.6)

    def test_semantically_different_near_lines_are_preserved(self):
        lines = ["I can go now.", "I cannot go now."]
        self.assertEqual(clean_text_lines(lines), lines)

    def test_spacy_model_is_loaded_only_once(self):
        fake_nlp = object()
        spacy_model_module._load_model_cached.cache_clear()
        with mock.patch.object(spacy_model_module.spacy, "load", return_value=fake_nlp) as load:
            first = spacy_model_module._load_model_cached("fake_model")
            second = spacy_model_module._load_model_cached("fake_model")
        self.assertIs(first, second)
        load.assert_called_once_with("fake_model")
        spacy_model_module._load_model_cached.cache_clear()

    def test_compact_translation_uses_one_ordered_request(self):
        captured = []

        def fake_ask(prompt, **kwargs):
            captured.append(prompt)
            response = {
                "translations": [
                    {"id": 1, "text": "Olá."},
                    {"id": 2, "text": "Tudo bem?"},
                ]
            }
            self.assertEqual(kwargs["valid_def"](response)["status"], "success")
            return response

        settings = {
            "whisper.detected_language": "en",
            "target_language": "Português brasileiro",
        }
        with (
            mock.patch.object(translation_module, "ask_gpt", side_effect=fake_ask),
            mock.patch.object(translation_module, "load_key", side_effect=lambda key: settings[key]),
        ):
            translated, original = translation_module.translate_lines(
                "Hello.\nHow are you?", [], [], None, "test theme"
            )
        self.assertEqual(len(captured), 1)
        self.assertEqual(original, "Hello.\nHow are you?")
        self.assertEqual(translated, "Olá.\nTudo bem?")
        self.assertNotIn("reflection", captured[0].lower())

    def test_short_video_translation_is_batched_into_one_call(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "split.txt"
            terminology = root / "terms.json"
            destination = root / "translation.xlsx"
            source.write_text("One line.\nSecond line.\nThird line.", encoding="utf-8")
            terminology.write_text('{"theme": "test", "terms": []}', encoding="utf-8")
            calls = []

            def fake_translate(chunk, *args):
                calls.append(chunk)
                lines = chunk.splitlines()
                return "\n".join(f"PT {line}" for line in lines), chunk

            with (
                mock.patch.object(translate_stage_module, "_3_2_SPLIT_BY_MEANING", str(source)),
                mock.patch.object(translate_stage_module, "_4_1_TERMINOLOGY", str(terminology)),
                mock.patch.object(translate_stage_module, "_4_2_TRANSLATION", str(destination)),
                mock.patch.object(translate_stage_module, "translate_lines", side_effect=fake_translate),
                mock.patch.object(
                    translate_stage_module, "search_things_to_note_in_prompt", return_value=None
                ),
                mock.patch.object(
                    translate_stage_module,
                    "load_key",
                    side_effect=lambda key: {
                        "translation.batch_chars": 6500,
                        "translation.batch_max_lines": 120,
                    }[key],
                ),
            ):
                translate_stage_module.translate_all.__wrapped__()

            frame = __import__("pandas").read_excel(destination)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(frame), 3)
            self.assertEqual(frame["Translation"].tolist()[0], "PT One line.")

    def test_display_translation_stage_has_no_sub_trim_dependency(self):
        source = Path(translate_stage_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("check_len_then_trim", source)
        self.assertNotIn("sub_trim", source)


if __name__ == "__main__":
    unittest.main()
