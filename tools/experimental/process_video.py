import sys
import time

from _bootstrap import configure_runtime

configure_runtime()

from core._1_ytdlp import download_video_ytdlp, find_video_files
from core import _2_asr
from core import _3_1_split_nlp
from core import _3_2_split_meaning
from core import _4_1_summarize
from core import _4_2_translate
from core import _5_split_sub
from core import _6_gen_sub
from core import _7_sub_into_vid

VIDEO_URL = "https://www.youtube.com/watch?v=wt4p2oalmRY&list=WL&index=79"


def main():
    print("=" * 60)
    print(" VideoLingo automatic subtitle processing")
    print("=" * 60)

    # Step 1: Download video
    print("\n[1/6] Downloading YouTube video...")
    download_video_ytdlp(VIDEO_URL, save_path="output", resolution="1080")
    print(f"   Video saved to: {find_video_files('output')}")

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
        sys.exit(1)
