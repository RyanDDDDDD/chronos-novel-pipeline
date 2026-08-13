import inspect

import pytest
from engine.setup_chat.research import recall_research, web_search


def test_recall_hit_formats(monkeypatch):
    import repositories
    from repositories.entities import ResearchChunk
    class FakeResearchRepo:
        def query(self, topic, top_k):
            return [ResearchChunk(text="企业统治", source="http://x", topic="世界观", score=0.1)]

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())
    out = recall_research.invoke({"topic": "谁统治"})
    assert "企业统治" in out and "http://x" in out


def test_recall_miss_returns_gate_hint(monkeypatch):
    import repositories
    class FakeResearchRepo:
        def query(self, topic, top_k):
            return []

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())
    out = recall_research.invoke({"topic": "未知"})
    assert "没有" in out and "联网" in out


@pytest.mark.asyncio
async def test_web_search_no_key(monkeypatch):
    def _raise(cfg):
        raise ValueError("未配置 Tavily key，无法联网检索。请在服务配置页填入 tavily_api_key。")

    monkeypatch.setattr("engine.setup_chat.research.build_search_provider", _raise)
    out = await web_search.ainvoke({"topic": "x"})
    assert "Tavily" in out and "未配置" in out


@pytest.mark.asyncio
async def test_web_search_persists_and_returns_answer(monkeypatch):
    from domain.search_provider import SearchHit, SearchResult

    stored = {}
    import repositories

    class FakeResearchRepo:
        def upsert(self, chunks):
            stored.update({"n": len(chunks)})
            return len(chunks)

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())

    class _FakeProvider:
        async def search(self, topic):
            return SearchResult(
                answer="七大企业统治",
                hits=[SearchHit(text="企业A 内容", url="http://a")],
            )

    monkeypatch.setattr(
        "engine.setup_chat.research.build_search_provider", lambda cfg: _FakeProvider(),
    )
    out = await web_search.ainvoke({"topic": "谁统治"})
    assert isinstance(out, str)
    assert "七大企业统治" in out
    assert stored["n"] == 1  # 检索结果写回数据库


@pytest.mark.asyncio
async def test_web_search_includes_images_in_text(monkeypatch):
    from domain.search_provider import SearchHit, SearchResult

    import repositories

    class FakeResearchRepo:
        def upsert(self, chunks):
            return len(chunks)

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())

    class _FakeProvider:
        async def search(self, topic):
            return SearchResult(
                answer="角色外貌概要",
                hits=[SearchHit(
                    text="设定正文", url="http://wiki",
                    images=[("http://img/char.png", "主角立绘")],
                )],
                top_images=[("http://img/top.jpg", None)],
            )

    monkeypatch.setattr(
        "engine.setup_chat.research.build_search_provider", lambda cfg: _FakeProvider(),
    )
    out = await web_search.ainvoke({"topic": "主角外貌"})
    assert isinstance(out, str)
    assert "角色外貌概要" in out
    assert "http://img/char.png" in out
    assert "http://img/top.jpg" in out
    assert "主角立绘" in out


@pytest.mark.asyncio
async def test_web_search_no_answer_skips_answer_line(monkeypatch):
    from domain.search_provider import SearchHit, SearchResult

    import repositories

    class FakeResearchRepo:
        def upsert(self, chunks):
            return len(chunks)

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())

    class _FakeProvider:
        async def search(self, topic):
            return SearchResult(
                answer=None,
                hits=[SearchHit(text="百度千帆结果正文", url="http://baidu-hit")],
            )

    monkeypatch.setattr(
        "engine.setup_chat.research.build_search_provider", lambda cfg: _FakeProvider(),
    )
    out = await web_search.ainvoke({"topic": "谁统治"})
    assert "答案：" not in out
    assert "百度千帆结果正文" in out
    assert "http://baidu-hit" in out


@pytest.mark.asyncio
async def test_web_search_downgrades_on_search_error(monkeypatch):
    class _FakeProvider:
        async def search(self, topic):
            raise RuntimeError("网络超时")

    monkeypatch.setattr(
        "engine.setup_chat.research.build_search_provider", lambda cfg: _FakeProvider(),
    )
    out = await web_search.ainvoke({"topic": "x"})
    assert "联网检索失败" in out


def test_list_characters_returns_sorted_deduped_names(monkeypatch):
    import repositories

    class FakeResearchRepo:
        def list_topics(self, category):
            assert category == "character"
            return ["乙", "甲"]

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())
    from engine.setup_chat.research import list_characters

    out = list_characters.invoke({})
    assert "甲" in out and "乙" in out


def test_list_characters_empty_returns_hint(monkeypatch):
    import repositories

    class FakeResearchRepo:
        def list_topics(self, category):
            return []

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())
    from engine.setup_chat.research import list_characters

    out = list_characters.invoke({})
    assert "暂无" in out


def test_list_characters_truncates_over_200_with_note(monkeypatch):
    import repositories

    class FakeResearchRepo:
        def list_topics(self, category):
            return [f"角色{i}" for i in range(250)]

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())
    from engine.setup_chat.research import list_characters

    out = list_characters.invoke({})
    assert "共 250 条" in out and "前 200" in out


def test_get_character_hit_returns_joined_text(monkeypatch):
    import repositories
    from repositories.entities import ResearchChunk

    class FakeResearchRepo:
        def get_chunks(self, category, topic=None):
            assert category == "character" and topic == "甲"
            return [ResearchChunk(text="性格：冷静\n口癖：口头禅X", topic="甲", category="character")]

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())
    from engine.setup_chat.research import get_character

    out = get_character.invoke({"name": "甲"})
    assert "冷静" in out and "口头禅X" in out


def test_get_character_miss_suggests_list_characters(monkeypatch):
    import repositories

    class FakeResearchRepo:
        def get_chunks(self, category, topic=None):
            return []

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())
    from engine.setup_chat.research import get_character

    out = get_character.invoke({"name": "不存在"})
    assert "未找到" in out and "list_characters" in out


def test_get_world_facts_returns_all_entries(monkeypatch):
    import repositories
    from repositories.entities import ResearchChunk

    class FakeResearchRepo:
        def get_chunks(self, category, topic=None):
            assert category == "world" and topic is None
            return [ResearchChunk(text="设定A", category="world"), ResearchChunk(text="设定B", category="world")]

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())
    from engine.setup_chat.research import get_world_facts

    out = get_world_facts.invoke({})
    assert "设定A" in out and "设定B" in out


def test_get_plot_points_empty_returns_hint(monkeypatch):
    import repositories

    class FakeResearchRepo:
        def get_chunks(self, category, topic=None):
            assert category == "plot"
            return []

    monkeypatch.setattr(repositories, "get_research_repo", lambda: FakeResearchRepo())
    from engine.setup_chat.research import get_plot_points

    out = get_plot_points.invoke({})
    assert "暂无" in out


def test_recall_research_docstring_points_to_exhaustive_tools():
    assert "list_characters" in recall_research.description


def test_agent_registers_research_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.agent.setup_chat_checkpoint_path",
        lambda: str(tmp_path / "cp.sqlite"),
    )
    import engine.setup_chat.agent as a

    src = inspect.getsource(a.build_agent)
    assert "recall_research" in src and "web_search" in src
    assert "list_characters" in src
    assert "get_character" in src
    assert "get_world_facts" in src
    assert "get_plot_points" in src
