"""The main author's submission: text + character status are spelled into .md（【摘要】块已随概要 agent 退役）。

状态推演已退役(2026-07-06)：角色状态章内不再逐拍演变，只在章开头 seed 一次；
落盘时按每个 stage 的在场角色名单直接渲染这份种子态（不再有 _derive_counts_upto/_micro_upto_beat 的增量裁剪）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src", "backend"))

from engine.author_loop.build import (  # noqa: E402
    _format_stage_state_block,
    save_author_loop_chapter,
)
from engine.state import assemble_chapter_file  # noqa: E402


def test_format_stage_state_block_includes_state():
    segment = {
        "stage_num": 1,
        "characters": ["甲"],
        "character_states": {"甲": {"psychology": "戒备", "clothing": "常服"}},
    }
    block = _format_stage_state_block(segment, chapter=1)
    assert "【摘要】" not in block  #概要 agent 已退役，不再产梗概
    assert "【角色状态】" in block and "**甲**" in block
    assert "着装：常服" in block
    assert "    - 着装：常服" in block


def test_format_stage_state_block_empty_when_no_characters():
    assert _format_stage_state_block({"stage_num": 1, "characters": []}, chapter=1) == ""


def test_assemble_with_extra_block_order():
    segs = [{"index": 0, "title": "起", "location": "寝殿", "text": "正文"}]
    extra = "- **【角色状态】**：\n  - **甲**：心理：稳"
    assembled = assemble_chapter_file(1, segs, md_block_provider=lambda i: extra)
    assert assembled.index("【地点场景】") < assembled.index("【角色状态】") < assembled.index("【过程描述】")


def test_save_author_loop_chapter_writes_text_and_state(tmp_path, monkeypatch):
    import engine.author_loop.build as build_mod
    import engine.author_loop.dialogue_mode.chapter_checkpoint as cp_mod
    import utils.paths as upaths

    cv = {
        "parts": ["第一拍正文"],
        "part_stage_idx": [0],
        "stages": [{"chapter": 2, "stage": 1, "characters": ["甲"]}],
        "part_character_states": [{"甲": {"psychology": "稳", "clothing": "袍"}}],
    }
    monkeypatch.setattr(cp_mod, "read_chapter_checkpoint_values", lambda _cp, _tid: cv)
    monkeypatch.setattr(build_mod, "author_loop_graph_checkpoint_path", lambda: str(tmp_path / "g.sqlite"))
    monkeypatch.setattr(build_mod, "fetch_chapter_outline", lambda ch: ("章", [{"index": 0, "title": "起", "location": "厅"}]))
    monkeypatch.setattr(upaths, "get_chapter_dir", lambda ch: str(tmp_path / "chapters" / f"第{ch}章"))
    monkeypatch.setattr(build_mod, "_export_prompt_dump", lambda ch: None)  #真子进程另测

    path = save_author_loop_chapter(2)
    body = open(path, encoding="utf-8").read()
    assert "第一拍正文" in body
    assert "【角色状态】" in body
    assert "**甲**" in body


def test_save_author_loop_chapter_uses_part_character_states_not_archive(monkeypatch, tmp_path):
    import engine.author_loop.build as build_mod
    import engine.author_loop.dialogue_mode.chapter_checkpoint as cp_mod
    import utils.paths as upaths

    cv = {
        "parts": ["正文0", "正文1"],
        "stages": [{"chapter": 1, "stage": 1, "characters": ["甲"]},
                   {"chapter": 1, "stage": 2, "characters": ["甲"]}],
        "part_stage_idx": [0, 1],
        "part_character_states": [
            {"甲": {"psychology": "紧张"}},
            {"甲": {"psychology": "平静"}},
        ],
    }
    called = {}

    def fake_resolve_card_state(*a, **k):
        called["hit"] = True
        return {}
    monkeypatch.setattr(build_mod, "resolve_card_state", fake_resolve_card_state, raising=False)
    monkeypatch.setattr(cp_mod, "read_chapter_checkpoint_values", lambda _cp, _tid: cv)
    monkeypatch.setattr(build_mod, "author_loop_graph_checkpoint_path", lambda: str(tmp_path / "g.sqlite"))
    monkeypatch.setattr(build_mod, "fetch_chapter_outline", lambda ch: ("章", [
        {"index": 0, "stage_num": 1, "title": "起", "location": "厅"},
        {"index": 1, "stage_num": 2, "title": "承", "location": "厅"},
    ]))
    monkeypatch.setattr(upaths, "get_chapter_dir", lambda ch: str(tmp_path / "chapters" / f"第{ch}章"))
    monkeypatch.setattr(build_mod, "_export_prompt_dump", lambda ch: None)

    path = save_author_loop_chapter(1)
    content = open(path, encoding="utf-8").read()
    assert "紧张" in content and "平静" in content
    assert "hit" not in called


def test_save_author_loop_chapter_headers_survive_skipped_empty_stage(tmp_path, monkeypatch):
    """stage2 正文为空被引擎跳过时(见 react_graph._author_prose_node)，parts 里只剩 stage1/stage3
    两条，part_stage_idx 记录真实来源 stage 下标——拼章必须仍能按真实 stage_num 查到各自的
    标题/地点，不能按 parts 的位置(0/1)去误当成 stages 列表位置(0/1/2)（本 bug 的复现）。"""
    import engine.author_loop.build as build_mod
    import engine.author_loop.dialogue_mode.chapter_checkpoint as cp_mod
    import utils.paths as upaths

    cv = {
        "parts": ["浴室场景正文", "客厅收尾正文"],
        "part_stage_idx": [0, 2],  #stage_idx=1(中间的卧室 stage)因空正文被引擎跳过
        "stages": [
            {"chapter": 2, "stage": 1, "characters": []},
            {"chapter": 2, "stage": 2, "characters": []},
            {"chapter": 2, "stage": 3, "characters": []},
        ],
    }
    monkeypatch.setattr(cp_mod, "read_chapter_checkpoint_values", lambda _cp, _tid: cv)
    monkeypatch.setattr(build_mod, "author_loop_graph_checkpoint_path", lambda: str(tmp_path / "g.sqlite"))
    monkeypatch.setattr(
        build_mod, "fetch_chapter_outline",
        lambda ch: ("章", [
            {"index": 0, "stage_num": 1, "title": "诱入", "location": "浴室"},
            {"index": 1, "stage_num": 2, "title": "缠斗", "location": "卧室"},
            {"index": 2, "stage_num": 3, "title": "收束", "location": "客厅"},
        ]),
    )
    monkeypatch.setattr(upaths, "get_chapter_dir", lambda ch: str(tmp_path / "chapters" / f"第{ch}章"))
    monkeypatch.setattr(build_mod, "_export_prompt_dump", lambda ch: None)  #真子进程另测

    path = save_author_loop_chapter(2)
    body = open(path, encoding="utf-8").read()

    #中间跳过的"缠斗"/卧室 stage 未产出正文，标题不应出现；
    #"收束"/客厅的标题必须紧挨着真正属于它的"客厅收尾正文"，不能被误当成跳过的 stage2。
    assert "缠斗" not in body and "卧室" not in body
    assert body.index("收束") < body.index("客厅收尾正文")
    assert body.count("### 【阶段") == 2


def test_export_prompt_dump_invokes_prompt_parse(tmp_path, monkeypatch):
    """保存时导出本章全量 prompt:有日志才拉 prompt_parse 子进程,-c/-o 参数正确。"""
    import subprocess

    import engine.author_loop.build as build_mod
    import utils.paths as upaths

    logs = tmp_path / "engine_server"
    logs.mkdir()
    (logs / "chapter_002_20260705_000000.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(upaths, "engine_logs_dir", lambda: str(logs))
    out_path = str(tmp_path / "parsed" / "chapter_002_latest.txt")
    monkeypatch.setattr(upaths, "prompt_dump_path", lambda ch: out_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(list(cmd)))

    build_mod._export_prompt_dump(2)
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[1].endswith("prompt_parse.py")
    assert cmd[cmd.index("-c") + 1] == "2"
    assert cmd[cmd.index("-o") + 1] == out_path

    #无日志的章直接跳过,不空转子进程
    build_mod._export_prompt_dump(99)
    assert len(calls) == 1
