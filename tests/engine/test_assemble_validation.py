"""Chapter assembly: assemble_chapter_file product structure (pure function, can be run natively)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

from engine.state import assemble_chapter_file  # noqa: E402


def _seg(index, title="", location="", text="正文"):
    return {"index": index, "title": title, "location": location, "text": text}


def test_title_segments_render_stage_blocks():
    segs = [_seg(0, "起", "寝殿", "甲"), _seg(1, "承", "回廊", "乙"), _seg(2, "合", "床榻", "丙")]
    assembled = assemble_chapter_file(1, segs)
    assert assembled.count("### 【阶段") == 3
    assert assembled.count("- **【过程描述】**") == 3
    assert assembled.count("- **【地点场景】**") == 3


def test_md_block_provider_inserts_after_location():
    segs = [_seg(0, "起", "寝殿", "甲")]
    assembled = assemble_chapter_file(1, segs, md_block_provider=lambda i: "【附加块】")
    #Additional blocks are inserted after the location and before the process description
    assert assembled.index("【地点场景】") < assembled.index("【附加块】") < assembled.index("【过程描述】")


def test_bare_text_segment_passthrough():
    segs = [_seg(0, text="纯过场文本")]
    assembled = assemble_chapter_file(1, segs)
    assert assembled == "纯过场文本"
