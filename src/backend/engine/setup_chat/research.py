"""Set up research grounding tools: recall_research (native library) / web_search
(Tavily / Baidu Qianfan AppBuilder, user-selected in service config, user gated)."""
from __future__ import annotations

from domain.search_provider import SearchHit, SearchResult, build_search_provider
from langchain_core.tools import tool
from utils.config import get_config

from engine.setup_chat.tool_args import GetCharacterArgs, RecallResearchArgs, WebSearchArgs

_TOP_K = 5
_MAX_LIST_ITEMS = 200
_MAX_IMAGES = 5


def _cap_and_join(lines: list[str], empty_msg: str) -> str:
    total = len(lines)
    shown = lines[:_MAX_LIST_ITEMS]
    body = "\n".join(shown) if shown else empty_msg
    if total > _MAX_LIST_ITEMS:
        body += f"\n（共 {total} 条，仅显示前 {_MAX_LIST_ITEMS} 条）"
    return body


def _hit_text_for_index(hit: SearchHit) -> str:
    """The research database only stores text; image captions are folded into the
    text for recall retrieval."""
    parts = [hit.text] if hit.text.strip() else []
    for _url, desc in hit.images:
        if desc:
            parts.append(f"[图片说明] {desc}")
    return "\n".join(parts)


def _format_search_text(result: SearchResult) -> str:
    sources = "\n".join(f"- {h.url}" for h in result.hits if h.url)
    if result.answer:
        text = f"联网检索结果：\n{result.answer}\n\n来源：\n{sources}"
    else:
        # No vendor-synthesized answer (e.g. Baidu Qianfan) -- list source snippets
        # instead of fabricating a summary; the agent reads these itself.
        snippet_lines = [f"- {h.url}\n  {h.text[:200]}" for h in result.hits if h.url]
        body = "\n".join(snippet_lines) if snippet_lines else "（无结果）"
        text = f"联网检索结果（来源摘要）：\n{body}"

    # Merge every image source (top-level + each hit's own), dedupe, then cap ONCE
    # here -- domain.search_provider._collect_images deliberately does not cap, so
    # each hit doesn't independently fill the quota and starve the others.
    seen: set[str] = set()
    images: list[tuple[str, str | None]] = []
    for url, desc in result.top_images:
        if url not in seen:
            seen.add(url)
            images.append((url, desc))
    for h in result.hits:
        for url, desc in h.images:
            if url not in seen:
                seen.add(url)
                images.append((url, desc))
    images = images[:_MAX_IMAGES]
    if not images:
        return text
    lines = [text, "\n相关图片（URL + 说明，供参考）："]
    for i, (url, desc) in enumerate(images, 1):
        line = f"{i}. {url}"
        if desc:
            line += f" — {desc}"
        lines.append(line)
    return "\n".join(lines)


@tool(args_schema=RecallResearchArgs)
def recall_research(topic: str) -> str:
    """
Check the local research database (information that has been previously searched online and stored). Adjust this tool first when you need external facts/canon.
    A hit will return data; a miss will prompt - At this time, you should [Ask the user whether to connect to the Internet], do not automatically connect to the Internet.
    穷举类问题（"这本小说都有哪些角色/世界观设定/剧情点"）请改用 list_characters /
    get_character / get_world_facts / get_plot_points——本工具是语义 top-5 检索，条目一多就会漏。"""
    from repositories import get_research_repo

    hits = get_research_repo().query(topic, top_k=_TOP_K)
    if not hits:
        return f"本地研究库没有「{topic}」的资料。如需联网检索，请告诉我，我再用 web_search。"
    lines = [f"[{h.source or '?'}] {h.text or ''}" for h in hits]
    return "本地研究记忆：\n" + "\n".join(lines)


@tool(args_schema=WebSearchArgs)
async def web_search(topic: str) -> str:
    """
Networked retrieval of external facts/canon (Tavily or Baidu Qianfan, per service config). [Only called with explicit consent from the user].
    The results will be stored in the local research database for future reuse, and the abstract + source will be returned; when a relevant image is hit, the URL/description will be written into the text."""
    try:
        provider = build_search_provider(get_config())
    except ValueError as exc:
        return str(exc)
    try:
        result = await provider.search(topic)
    except Exception as exc:  # noqa: BLE001 — 网络/超时/API 错误降级，不阻断对话
        return f"联网检索失败：{exc}"

    chunks_data = [
        {"text": text, "topic": topic, "source": h.url}
        for h in result.hits
        if (text := _hit_text_for_index(h))
    ]
    if chunks_data:
        try:
            from repositories import get_research_repo
            from repositories.entities import ResearchChunk

            get_research_repo().upsert([
                ResearchChunk(text=c["text"], topic=c["topic"], source=c["source"])
                for c in chunks_data
            ])
        except (OSError, ValueError, RuntimeError):
            pass  # 入库失败不影响本次返回

    return _format_search_text(result)


@tool
def list_characters() -> str:
    """列出导入小说 RAG 库里已提炼出的全部角色名（去重，穷举而非语义近似，最多 200 个）。
    需要"这本小说都有哪些角色"这类穷举类问题时优先用这个，而非 recall_research（语义 top-5
    检索角色多了会漏）。查到名字后用 get_character(name) 取该角色的详细性格/口癖。"""
    from repositories import get_research_repo
    from repositories.entities import ResearchCategory

    names = get_research_repo().list_topics(ResearchCategory.CHARACTER)
    return _cap_and_join(sorted(names), "本地暂无导入小说的角色记录（尚未导入或该小说没有角色设定）。")


@tool(args_schema=GetCharacterArgs)
def get_character(name: str) -> str:
    """精确取导入小说 RAG 库里某个角色的性格/口癖（精确匹配角色名，不做模糊/子串匹配）。
    未命中时请先调用 list_characters 确认准确名字再重试。"""
    from repositories import get_research_repo
    from repositories.entities import ResearchCategory

    chunks = get_research_repo().get_chunks(ResearchCategory.CHARACTER, topic=name)
    if not chunks:
        return f"未找到角色「{name}」，请先调用 list_characters 确认准确名字。"
    return "\n".join(c.text for c in chunks)


@tool
def get_world_facts() -> str:
    """列出导入小说 RAG 库里已提炼出的全部世界观条目（穷举而非语义近似，最多 200 条）。
    需要穷举该小说的世界观设定时优先用这个，而非 recall_research。"""
    from repositories import get_research_repo
    from repositories.entities import ResearchCategory

    chunks = get_research_repo().get_chunks(ResearchCategory.WORLD)
    return _cap_and_join(
        [c.text for c in chunks], "本地暂无导入小说的世界观记录（尚未导入或该小说没有世界观设定）。",
    )


@tool
def get_plot_points() -> str:
    """列出导入小说 RAG 库里已提炼出的全部剧情点（穷举而非语义近似，最多 200 条）。
    需要穷举该小说的剧情脉络时优先用这个，而非 recall_research。"""
    from repositories import get_research_repo
    from repositories.entities import ResearchCategory

    chunks = get_research_repo().get_chunks(ResearchCategory.PLOT)
    return _cap_and_join(
        [c.text for c in chunks], "本地暂无导入小说的剧情记录（尚未导入或该小说没有剧情要点）。",
    )
