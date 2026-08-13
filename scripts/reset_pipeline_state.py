"""重置 pipeline 状态。

用法：
    uv run python scripts/reset_pipeline_state.py
        仅重置服务器运行时状态 pipeline_state.json（pre-commit hook 内部调用）。
        **不触碰 chapters/ 下的任何文件**——章节产物（角色档案、进度、断点缓存）
        均为 gitignore 的本地运行物，提交时无需、也不应被清除。

    uv run python scripts/reset_pipeline_state.py --chapter 1
        重置状态 + 删除第1章的 agent 文本产物（*.md）与 temp/ 断点缓存；
        **保留 characters/** 下的角色档案 JSON，下次重跑不必重建档案。
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 独立脚本：pre-commit 钩子用裸 python 调用（无 editable 安装），
# 显式把 src/backend 加入路径，确保能 import 后端包。
sys.path.insert(0, os.path.join(ROOT, "src", "backend"))

from domain.usage import get_pipeline_state_path  # noqa: E402

CHAPTERS_DIR = os.path.join(ROOT, "chapters")

# pipeline_state.json 的运行时 schema 为 {consumed_poses, plugin_usage}（防重复注入用）。
# 重置即清空为 {}，引擎 _load 容错为空、按需重建。
INITIAL_STATE: dict = {}


def reset_state():
    state_path = get_pipeline_state_path()
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(INITIAL_STATE, f, ensure_ascii=False, indent=2)
    print(f"已重置: {state_path}")


def delete_chapter_outputs(chapter: int):
    """
删除 agent 生成的章节文本与 temp 缓存，保留 characters/ 角色档案。"""

    chapter_dir = Path(CHAPTERS_DIR) / f"第{chapter}章"
    if not chapter_dir.is_dir():
        print(f"章节目录不存在，跳过文件删除: {chapter_dir}")
        return

    removed_md = 0
    for md in chapter_dir.rglob("*.md"):
        if md.relative_to(chapter_dir).parts[:1] == ("characters",):
            continue
        md.unlink()
        removed_md += 1

    temp_dir = chapter_dir / "temp"
    temp_removed = temp_dir.is_dir()
    if temp_removed:
        shutil.rmtree(temp_dir)

    detail = f"删除 {removed_md} 个 .md"
    if temp_removed:
        detail += ", temp/"
    print(f"已清理第{chapter}章 agent 产物: {detail}（保留 characters/）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重置 pipeline 状态")
    parser.add_argument(
        "--chapter",
        type=int,
        default=None,
        help="同时删除指定章节的 agent 文本产物（*.md、temp/），保留 characters/",
    )
    args = parser.parse_args()

    reset_state()
    if args.chapter is not None:
        delete_chapter_outputs(args.chapter)
