from utils.expand_report import (
    analyze_chapter,
    cn_chars,
    prose_from_manuscript,
)


def test_cn_chars_strips_whitespace():
    assert cn_chars("甲乙 丙\n丁") == 4


def test_prose_from_manuscript_extracts_process_blocks():
    md = (
        "### 【阶段一：试衣】\n\n"
        "- **【地点场景】**：试衣间\n\n"
        "- **【过程描述】**：叙事甲。\n\n"
        "---\n\n"
        "### 【阶段二：离场】\n\n"
        "- **【过程描述】**：叙事乙。"
    )
    assert prose_from_manuscript(md) == "叙事甲。\n\n叙事乙。"


def test_analyze_chapter_aggregates_beats():
    ch = {
        "chapter": 1,
        "title": "测",
        "stages": [
            {
                "stage_num": 1,
                "beats": [
                    {"text": "底稿甲"},
                    {"text": "底稿乙"},
                ],
            },
        ],
    }
    report = analyze_chapter(ch)
    assert report.beat_chars == cn_chars("底稿甲") + cn_chars("底稿乙")
    assert len(report.beats) == 2
    assert report.stages[0].beat_count == 2
