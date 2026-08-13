"""行驱动模式·单拍输入 dataclass(构建期预建的分拍底稿)。

文风(prose_style)已改走整章 system 一次注入(见 react_graph.build_system_prompt),
不再逐拍复制进 BeatInput。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BeatInput:
    """单拍输入（构建期预建的分拍底稿 + 在场名单）。台词(若该拍设计了)已直接织入 beat_intent 正文，
    不再单独携带。"""

    beat_intent: str
    characters: list[str] = field(default_factory=list)
    chapter: int = 0
    stage: int = 0
    sensation_notes: list[str] = field(default_factory=list)  #体感软引导(仿动作方案生理感受),非硬约束
    dialogue_draft: str = ""  #构建期已生成的联合台词草稿，运行期零额外调用直接读（见 dialogue_draft.py）


@dataclass
class StageInput:
    """一个 stage 的输入(构建期预建的分拍底稿聚合,逐 stage 批量交给主笔)。"""

    chapter: int
    stage: int
    characters: list[str] = field(default_factory=list)
    beats: list[BeatInput] = field(default_factory=list)
