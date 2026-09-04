import shutil

from _bootstrap import configure_runtime

configure_runtime()

from core._1_ytdlp import find_video_files, write_input_manifest
from core import _2_asr
from core import _3_1_split_nlp
from core import _3_2_split_meaning
from core import _4_1_summarize
from core import _4_2_translate
from core import _5_split_sub
from core import _6_gen_sub
from core import _7_sub_into_vid

print("=" * 60)
print(" VideoLingo process existing video")
print("=" * 60)

video_file = find_video_files("output")
write_input_manifest(video_file, "video", "output")
print(f"\n[1/6] Using video: {video_file}")

print("\n[2/6] WhisperX word-level transcription...")
_2_asr.transcribe()

print("\n[3/6] Sentence segmentation...")
_3_1_split_nlp.split_by_spacy()
_3_2_split_meaning.split_sentences_by_meaning()

print("\n[4/6] Summarization and translation...")
_4_1_summarize.get_summary()
_4_2_translate.translate_all()

print("\n[5/6] Cutting and aligning subtitles...")
_5_split_sub.split_for_sub_main()
_6_gen_sub.align_timestamp_main()

print("\n[6/6] Merging subtitles into video...")
_7_sub_into_vid.merge_subtitles_to_video()

output_file = os.path.join("output", "output_sub.mp4")
final_file = os.path.join(project_root, "spider_test_60s_bilingual.mp4")
if os.path.exists(output_file):
    shutil.copy2(output_file, final_file)
    print(f"\nCopied to: {final_file}")

print("\n" + "=" * 60)
print(" Done!")
print("=" * 60)
