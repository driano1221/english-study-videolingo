import shutil

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

URL = "https://www.youtube.com/watch?v=wt4p2oalmRY&list=WL&index=79"

print("=" * 60)
print(" VideoLingo reprocess - spider web video")
print("=" * 60)

print("\n[1/6] Downloading YouTube video...")
download_video_ytdlp(URL, save_path="output", resolution="1080")
print(f"   Video saved to: {find_video_files('output')}")

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

# Backup result with timestamp
import datetime
output_file = os.path.join("output", "output_sub.mp4")
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
final_file = os.path.join(project_root, f"Is_spider_web_really_stronger_than_steel_bilingual_{timestamp}.mp4")
if os.path.exists(output_file):
    shutil.copy2(output_file, final_file)
    print(f"\nCopied to: {final_file}")

print("\n" + "=" * 60)
print(" Done! Check the output/ folder.")
print("=" * 60)
