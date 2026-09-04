import sys
import json

from _bootstrap import configure_runtime

configure_runtime()

# Configure UTF-8 console output on Windows
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from core._1_ytdlp import find_video_files, write_input_manifest
from core import _2_asr
from core import _3_1_split_nlp
from core import _3_2_split_meaning
from core import _4_1_summarize
from core import _4_2_translate
from core import _5_split_sub
from core import _6_gen_sub
from core import _7_sub_into_vid


def main():
    print("=" * 60)
    print(" VideoLingo subtitle processing (post-download)")
    print("=" * 60)

    # Ensure manifest is written for the existing video
    video_file = find_video_files("output")
    write_input_manifest(video_file, "video", "output")
    print(f"\n[1/6] Using downloaded video: {video_file}")

    # Step 2: Transcribe with WhisperX
    print("\n[2/6] WhisperX word-level transcription...")
    _2_asr.transcribe()

    # Step 3: Sentence segmentation
    print("\n[3/6] Sentence segmentation (NLP + LLM)...")
    _3_1_split_nlp.split_by_spacy()
    _3_2_split_meaning.split_sentences_by_meaning()

    # Step 4: Summarize and translate
    print("\n[4/6] Summarization and translation...")
    _4_1_summarize.get_summary()
    _4_2_translate.translate_all()

    # Step 5: Split and align subtitles
    print("\n[5/6] Cutting and aligning subtitles...")
    _5_split_sub.split_for_sub_main()
    _6_gen_sub.align_timestamp_main()

    # Step 6: Burn subtitles into video
    print("\n[6/6] Merging subtitles into video...")
    _7_sub_into_vid.merge_subtitles_to_video()

    print("\n" + "=" * 60)
    print(" Done! Check the output/ folder.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
