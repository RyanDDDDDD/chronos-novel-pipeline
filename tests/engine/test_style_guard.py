"""正文机械护栏：禁用句式编译/匹配测试。"""
from engine.execution.style_guard import compile_negative_patterns, find_violation


def test_wildcard_pattern_matches_filled_content():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    match = find_violation("他不是喜欢她，而是习惯了。", patterns)
    assert match is not None


def test_wildcard_pattern_no_match_on_clean_text():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    assert find_violation("今天天气很好。", patterns) is None


def test_enumeration_pattern_matches_any_option():
    patterns = compile_negative_patterns("- `{理智|本能}崩溃了`")
    assert find_violation("她的理智崩溃了。", patterns) is not None
    assert find_violation("她的本能崩溃了。", patterns) is not None
    assert find_violation("她的耐心崩溃了。", patterns) is None


def test_literal_pattern_matches_exact_string_only():
    patterns = compile_negative_patterns("- `这一次，他动了。`")
    assert find_violation("这一次，他动了。转身离开。", patterns) is not None
    assert find_violation("这一次，他没动。", patterns) is None


def test_wildcard_does_not_cross_sentence_boundary():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    #"不是" 和 "而是" 分属两个独立句子（中间是句号不是逗号），不该被跨句匹配
    assert find_violation("这不是重点。而是另一件事。", patterns) is None


def test_non_bullet_lines_and_word_ban_section_are_ignored():
    card = (
        "## 禁用词汇\n"
        "- 「微不可察」及变体\n\n"
        "## 禁用句式\n"
        "- `不是【】，而是【】`\n"
    )
    patterns = compile_negative_patterns(card)
    assert len(patterns) == 1


from engine.execution.style_guard import expand_to_sentence


def test_expand_to_sentence_isolates_matched_sentence():
    text = "他说了一句话。他不是喜欢她，而是习惯了。转身走了。"
    start = text.index("不是喜欢她")
    end = start + len("不是喜欢她，而是习惯了")
    left, right = expand_to_sentence(text, (start, end))
    assert text[left:right] == "他不是喜欢她，而是习惯了。"


def test_expand_to_sentence_handles_match_at_text_start():
    text = "不是喜欢她，而是习惯了。转身走了。"
    start = text.index("不是喜欢她")
    end = start + len("不是喜欢她，而是习惯了")
    left, right = expand_to_sentence(text, (start, end))
    assert left == 0
    assert text[left:right] == "不是喜欢她，而是习惯了。"


def test_expand_to_sentence_handles_no_trailing_punctuation():
    text = "他说了一句话。他不是喜欢她，而是习惯了"
    start = text.index("不是喜欢她")
    end = len(text)
    left, right = expand_to_sentence(text, (start, end))
    assert right == len(text)
    assert text[left:right] == "他不是喜欢她，而是习惯了"


import pytest
from engine.execution.style_guard import get_compiled_patterns, guarded_stream


async def _aiter(tokens):
    for t in tokens:
        yield t


@pytest.mark.asyncio
async def test_guarded_stream_passes_clean_text_unchanged():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    calls = []

    async def rewrite(context, sentence, trigger):
        calls.append((context, sentence))
        return sentence

    exhausted = []
    tokens = list("今天天气很好。")
    out = []
    async for piece in guarded_stream(
        _aiter(tokens), patterns=patterns, rewrite=rewrite,
        on_exhausted=exhausted.append, flush_every=4,
    ):
        out.append(piece)
    assert "".join(out) == "今天天气很好。"
    assert calls == []
    assert exhausted == []


@pytest.mark.asyncio
async def test_guarded_stream_rewrites_on_violation():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")

    async def rewrite(context, sentence, trigger):
        return "他其实很在意她。"

    exhausted = []
    tokens = list("他不是喜欢她，而是习惯了。")
    out = []
    async for piece in guarded_stream(
        _aiter(tokens), patterns=patterns, rewrite=rewrite,
        on_exhausted=exhausted.append, flush_every=4,
    ):
        out.append(piece)
    result = "".join(out)
    assert "不是" not in result
    assert "他其实很在意她。" in result
    assert exhausted == []


@pytest.mark.asyncio
async def test_guarded_stream_gives_up_after_two_rewrites():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    calls = []

    async def rewrite(context, sentence, trigger):
        calls.append(sentence)
        return "还是不是喜欢她，而是习惯了。"

    exhausted = []
    original = "他不是喜欢她，而是习惯了。"
    out = []
    async for piece in guarded_stream(
        _aiter(list(original)), patterns=patterns, rewrite=rewrite,
        on_exhausted=exhausted.append, flush_every=4,
    ):
        out.append(piece)
    result = "".join(out)
    assert result == "还是不是喜欢她，而是习惯了。"  #耗尽不再回退，接受最后一次重写产出
    assert len(calls) == 2  #恰好重试 2 次
    assert exhausted == [original]


@pytest.mark.asyncio
async def test_guarded_stream_flushes_on_paragraph_break_before_flush_every():
    async def rewrite(context, sentence, trigger):
        return sentence

    tokens = list("第一段。\n\n第二段还没写完")
    chunks = []
    async for piece in guarded_stream(
        _aiter(tokens), patterns=[], rewrite=rewrite,
        on_exhausted=lambda s: None, flush_every=4,
    ):
        chunks.append(piece)
    assert chunks[0] == "第一段。\n\n"
    assert "".join(chunks) == "第一段。\n\n第二段还没写完"


def test_get_compiled_patterns_compiles_hardcoded_list_and_caches():
    first = get_compiled_patterns()
    second = get_compiled_patterns()
    assert first is second
    assert len(first) >= 15


def test_stunned_then_transition_pattern_matches():
    patterns = get_compiled_patterns()
    text = "筱雨愣了一下。然后她笑了。"
    assert find_violation(text, patterns) is not None


def test_dash_that_kind_of_self_gloss_pattern_matches():
    patterns = get_compiled_patterns()
    text = "她笑了——那种从喉咙深处发出的，带着了然和期待的笑。"
    assert find_violation(text, patterns) is not None


def test_stunned_then_and_self_gloss_patterns_no_false_positive_on_clean_text():
    patterns = get_compiled_patterns()
    assert find_violation("她愣了一下，随即转身走开。", patterns) is None
    assert find_violation("她说的是那种朴素的道理。", patterns) is None


def test_before_after_contrast_summary_pattern_matches():
    patterns = get_compiled_patterns()
    text = "原本死气沉沉的门厅，这下全被这脆生生的笑声给掀翻了。"
    assert find_violation(text, patterns) is not None


def test_before_after_contrast_summary_pattern_no_false_positive_on_clean_text():
    patterns = get_compiled_patterns()
    assert find_violation("原本约好周五见面，后来又改到了周六。", patterns) is None


def test_vague_second_count_pause_pattern_matches():
    patterns = get_compiled_patterns()
    assert find_violation("空气安静了两三秒。", patterns) is not None
    assert find_violation("柔柔不动了，沉默了一两秒。", patterns) is not None


def test_stood_there_no_move_pattern_matches():
    patterns = get_compiled_patterns()
    text = "柔柔站在那里，没有动。"
    assert find_violation(text, patterns) is not None


def test_pause_patterns_no_false_positive_on_clean_text():
    patterns = get_compiled_patterns()
    assert find_violation("她安静地看着窗外，过了很久才开口。", patterns) is None
    assert find_violation("她站在那里，盯着他看。", patterns) is None


def test_silent_lips_guess_pattern_matches():
    patterns = get_compiled_patterns()
    text = "柔柔的嘴唇动了动，却没发出声音，像是还没想好该说什么。"
    assert find_violation(text, patterns) is not None


def test_silent_lips_guess_pattern_no_false_positive_on_clean_text():
    patterns = get_compiled_patterns()
    assert find_violation("她嘴唇动了动，说出了那句话。", patterns) is None


def test_deep_breath_pattern_matches():
    patterns = get_compiled_patterns()
    assert find_violation("她深吸一口气，把话咽了回去。", patterns) is not None
    assert find_violation("她深吸了一口气，才缓缓开口。", patterns) is not None


def test_deep_breath_pattern_no_false_positive_on_clean_text():
    patterns = get_compiled_patterns()
    assert find_violation("她需要先确认一下。", patterns) is None


def test_pause_briefly_pattern_matches():
    patterns = get_compiled_patterns()
    assert find_violation("她的动作顿了顿，才继续往下说。", patterns) is not None
    assert find_violation("他顿了顿，然后开口。", patterns) is not None


def test_pause_briefly_pattern_no_false_positive_on_clean_text():
    patterns = get_compiled_patterns()
    assert find_violation("他停了一下，继续往前走。", patterns) is None


def test_stacked_qualifier_pattern_matches():
    patterns = get_compiled_patterns()
    text = "那眼神——不是生气。不是委屈。是一种——「我也想要」的、亮晶晶的、带着期待的湿润。"
    assert find_violation(text, patterns) is not None


def test_stacked_qualifier_pattern_no_false_positive_on_clean_text():
    patterns = get_compiled_patterns()
    text = "她穿着一件洗得发白的、袖口磨破的外套。"
    assert find_violation(text, patterns) is None


from engine.execution.style_guard import WordDensityGuard


def test_word_density_check_returns_none_under_threshold():
    guard = WordDensityGuard(thresholds={"仿佛": 1}, window_chars=100)
    guard.record("他仿佛")
    assert guard.check("看到了什么") == []


def test_word_density_check_returns_hit_when_over_threshold():
    guard = WordDensityGuard(thresholds={"仿佛": 1}, window_chars=100)
    guard.record("仿佛")  # 已计入窗口 1 次，恰好等于阈值
    hits = guard.check("他仿佛笑了")  # 窗口内(1) + 本次(1) = 2 > 1
    assert len(hits) == 1
    word, idx = hits[0]
    assert word == "仿佛"
    assert idx == "他仿佛笑了".index("仿佛")


def test_word_density_check_returns_all_simultaneously_over_threshold_words():
    """同一段文本里若有多个词同时超标，check() 要一次性全部收集，不能只报字典顺序最前的一个——
    否则合并重写循环里排在后面的词要等下一轮才被发现，等不到下一轮就被 on_exhausted 放行了。"""
    guard = WordDensityGuard(thresholds={"仿佛": 0, "似乎": 0, "骤然": 0}, window_chars=1000)
    hits = guard.check("他仿佛骤然愣住，似乎想说什么。")
    assert {word for word, _idx in hits} == {"仿佛", "似乎", "骤然"}


def test_word_density_flags_stacked_similes():
    """连续几个「跟……似的/一样」明喻堆叠是常见 AI 味,靠词密度而非单句规则拦。"""
    guard = WordDensityGuard(thresholds={"似的": 2}, window_chars=1000)
    guard.record("娜娜跟只考拉似的扑过来，声音跟毛刷子似的蹭着脸。")  # 窗口内已 2 次「似的」
    hits = guard.check("笑得跟脆铃似的。")  # 窗口(2) + 本次(1) = 3 > 2
    assert len(hits) == 1
    word, _idx = hits[0]
    assert word == "似的"


def test_word_density_phrase_pattern_matches_grammatical_insertion():
    """「压低【】声音」是短语模式,要兜住"压低了声音"这种中间插字的变体，
    不能只认字面的"压低声音"四个字连着出现。"""
    guard = WordDensityGuard(thresholds={"压低【】声音": 0}, window_chars=1000)
    hits = guard.check("她压低了声音说道。")
    assert len(hits) == 1
    word, idx = hits[0]
    assert word == "压低【】声音"
    assert idx == "她压低了声音说道。".index("压低了声音")


def test_word_density_phrase_pattern_matches_no_gap():
    guard = WordDensityGuard(thresholds={"压低【】声音": 0}, window_chars=1000)
    assert guard.check("他压低声音警告她。") != []


def test_word_density_phrase_pattern_respects_gap_span():
    """插字超过 _PHRASE_GAP_SPAN 就不算同一个短语了，避免通配符吞掉无关内容。"""
    guard = WordDensityGuard(thresholds={"压低【】声音": 0}, window_chars=1000)
    assert guard.check("他压低了好久好久的声音。") == []


def test_word_density_phrase_pattern_enum_only_without_wildcard_gap():
    """key 只用 {A|B} 枚举、不含【】间隙的短语（如"指节{发|泛}白"）也要走 DSL 编译，
    不能因为没有【就被误判成字面词——回归 _compile_density_key 曾经的判断条件 bug。"""
    guard = WordDensityGuard(thresholds={"指节{发|泛}白": 0}, window_chars=1000)
    hit_fa = guard.check("他指节发白，用力攥紧了拳头。")  # check() 只读，不提交，可连续探测
    hit_fan = guard.check("她指节泛白，死死抓着栏杆。")
    assert hit_fa
    assert hit_fan
    assert hit_fan[0][0] == "指节{发|泛}白"


def test_word_density_phrase_pattern_enum_only_no_false_positive_on_clean_text():
    guard = WordDensityGuard(thresholds={"指节{发|泛}白": 0}, window_chars=1000)
    assert guard.check("他关节有点疼，去医院看了看。") == []


def test_word_density_reset_word_clears_count():
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=100)
    guard.record("仿佛")
    assert guard.check("仿佛") != []  # 1(窗口) + 1(本次) = 2 > 0
    guard.reset_word("仿佛")
    assert guard.check("") == []  # 计数已清零，0 + 0 = 0，不 > 0


def test_word_density_window_trims_old_chunks_and_decrements_count():
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=5)
    guard.record("仿佛")    # len=2, total=2
    guard.record("12345")  # len=5, total=7>5 -> 裁掉最早的 "仿佛" 块，total=5，仿佛计数回到 0
    assert guard.check("") == []


@pytest.mark.asyncio
async def test_guarded_stream_rewrites_on_word_density_violation():
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=1000)

    async def rewrite(context, sentence, trigger):
        return "他犹豫着开口。"

    exhausted = []
    tokens = list("他仿佛想说什么。")
    out = []
    async for piece in guarded_stream(
        _aiter(tokens), patterns=[], rewrite=rewrite,
        on_exhausted=exhausted.append, flush_every=4, word_guard=guard,
    ):
        out.append(piece)
    result = "".join(out)
    assert "仿佛" not in result
    assert "他犹豫着开口。" in result
    assert exhausted == []


@pytest.mark.asyncio
async def test_guarded_stream_gives_up_on_word_density_after_two_rewrites():
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=1000)
    calls = []

    async def rewrite(context, sentence, trigger):
        calls.append(sentence)
        return "他仿佛还想说什么。"  # 重写仍带回同一个词

    exhausted = []
    original = "他仿佛想说什么。"
    out = []
    async for piece in guarded_stream(
        _aiter(list(original)), patterns=[], rewrite=rewrite,
        on_exhausted=exhausted.append, flush_every=4, word_guard=guard,
    ):
        out.append(piece)
    result = "".join(out)
    assert result == "他仿佛还想说什么。"  # 耗尽不再回退，接受最后一次重写产出
    assert len(calls) == 2  # 恰好重试 2 次
    assert exhausted == [original]


@pytest.mark.asyncio
async def test_guarded_stream_word_guard_none_is_noop():
    """word_guard 默认 None 时完全跳过词密度检查，行为等同不传该参数。"""
    async def rewrite(context, sentence, trigger):
        return sentence

    tokens = list("他仿佛仿佛仿佛想说什么。")
    out = []
    async for piece in guarded_stream(
        _aiter(tokens), patterns=[], rewrite=rewrite,
        on_exhausted=lambda s: None, flush_every=4,
    ):
        out.append(piece)
    assert "".join(out) == "他仿佛仿佛仿佛想说什么。"


from engine.execution.style_guard import WordDensityGuardSnapshot


def test_word_density_guard_snapshot_restore_roundtrip():
    guard = WordDensityGuard(thresholds={"仿佛": 5}, window_chars=1000)
    guard.record("仿佛" * 2)
    snap = guard.snapshot()

    guard.record("仿佛" * 3)
    # 5 already at the limit; one more in the probe exceeds (check needs the word in text to locate)
    assert guard.check("仿佛") != []

    guard.restore(snap)
    # back to 2; probe of 1 more → projected 3 <= 5
    assert guard.check("仿佛") == []


def test_word_density_guard_snapshot_is_a_copy_not_a_live_view():
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=1000)
    guard.record("仿佛")
    snap = guard.snapshot()

    guard.record("仿佛")  # 修改原实例
    assert snap.counts["仿佛"] == 1  # 快照本身不受影响
    assert snap.chunks == ["仿佛"]


def test_word_density_guard_restore_preserves_instance_identity():
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=1000)
    snap_empty = guard.snapshot()
    guard.record("仿佛")

    same_guard = guard
    guard.restore(snap_empty)
    assert same_guard is guard  # restore 原地改写，不是换新实例
    assert guard.check("") == []

from engine.execution.style_guard import guard_text


@pytest.mark.asyncio
async def test_guard_text_passes_clean_text_unchanged():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    calls = []

    async def rewrite(context, sentence, trigger):
        calls.append((context, sentence))
        return sentence

    exhausted = []
    result = await guard_text(
        "今天天气很好。", patterns=patterns, rewrite=rewrite, on_exhausted=exhausted.append,
    )
    assert result == "今天天气很好。"
    assert calls == []
    assert exhausted == []


@pytest.mark.asyncio
async def test_guard_text_rewrites_on_pattern_violation():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")

    async def rewrite(context, sentence, trigger):
        return "他其实很在意她。"

    exhausted = []
    result = await guard_text(
        "他不是喜欢她，而是习惯了。", patterns=patterns, rewrite=rewrite, on_exhausted=exhausted.append,
    )
    assert "不是" not in result
    assert result == "他其实很在意她。"
    assert exhausted == []


@pytest.mark.asyncio
async def test_guard_text_gives_up_after_two_rewrites():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    calls = []

    async def rewrite(context, sentence, trigger):
        calls.append(sentence)
        return "还是不是喜欢她，而是习惯了。"

    exhausted = []
    original = "他不是喜欢她，而是习惯了。"
    result = await guard_text(
        original, patterns=patterns, rewrite=rewrite, on_exhausted=exhausted.append,
    )
    assert result == "还是不是喜欢她，而是习惯了。"  # 耗尽不再回退，接受最后一次重写产出
    assert len(calls) == 2
    assert exhausted == [original]


@pytest.mark.asyncio
async def test_guard_text_rewrites_on_word_density_violation():
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=1000)

    async def rewrite(context, sentence, trigger):
        return "他犹豫着开口。"

    exhausted = []
    result = await guard_text(
        "他仿佛想说什么。", patterns=[], rewrite=rewrite, on_exhausted=exhausted.append, word_guard=guard,
    )
    assert "仿佛" not in result
    assert exhausted == []


@pytest.mark.asyncio
async def test_guard_text_records_final_result_into_word_guard():
    guard = WordDensityGuard(thresholds={"仿佛": 5}, window_chars=1000)

    async def rewrite(context, sentence, trigger):
        return sentence

    await guard_text("仿佛", patterns=[], rewrite=rewrite, on_exhausted=lambda s: None, word_guard=guard)
    # 1(recorded) + 5(probe) > 5 -- proves record ran (check needs the word in probe text to locate)
    assert guard.check("仿佛" * 5) != []


@pytest.mark.asyncio
async def test_guard_text_passes_context_through_to_rewrite():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    seen_context = []

    async def rewrite(context, sentence, trigger):
        seen_context.append(context)
        return "改写后。"

    await guard_text(
        "他不是喜欢她，而是习惯了。", patterns=patterns, rewrite=rewrite,
        on_exhausted=lambda s: None, context="上文尾巴",
    )
    assert seen_context == ["上文尾巴"]


@pytest.mark.asyncio
async def test_guard_text_defaults_context_to_empty_string():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    seen_context = []

    async def rewrite(context, sentence, trigger):
        seen_context.append(context)
        return "改写后。"

    await guard_text(
        "他不是喜欢她，而是习惯了。", patterns=patterns, rewrite=rewrite, on_exhausted=lambda s: None,
    )
    assert seen_context == [""]


@pytest.mark.asyncio
async def test_guard_text_passes_matched_text_as_trigger_for_pattern_violation():
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    seen_triggers = []

    async def rewrite(context, sentence, trigger):
        seen_triggers.append(trigger)
        return "改写后。"

    await guard_text(
        "他不是喜欢她，而是习惯了。", patterns=patterns, rewrite=rewrite, on_exhausted=lambda s: None,
    )
    assert seen_triggers == ["不是喜欢她，而是习惯了"]  # find_violation 的 match.group()


@pytest.mark.asyncio
async def test_guard_text_passes_the_word_as_trigger_for_word_density_violation():
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=1000)
    seen_triggers = []

    async def rewrite(context, sentence, trigger):
        seen_triggers.append(trigger)
        return "他犹豫着开口。"

    await guard_text(
        "他仿佛想说什么。", patterns=[], rewrite=rewrite, on_exhausted=lambda s: None, word_guard=guard,
    )
    assert seen_triggers == ["仿佛"]


@pytest.mark.asyncio
async def test_guard_text_updates_trigger_on_retry_when_hit_changes():
    """第一次重写引入了另一个超标词，第二次重试时 trigger 应该是新命中的那个词，不是第一次的。"""
    guard = WordDensityGuard(thresholds={"仿佛": 0, "似乎": 0}, window_chars=1000)
    seen_triggers = []

    async def rewrite(context, sentence, trigger):
        seen_triggers.append(trigger)
        return "他似乎想说什么。"  # 重写把 "仿佛" 换成了另一个同样超标的词 "似乎"

    await guard_text(
        "他仿佛想说什么。", patterns=[], rewrite=rewrite, on_exhausted=lambda s: None, word_guard=guard,
    )
    assert seen_triggers == ["仿佛", "似乎"]


@pytest.mark.asyncio
async def test_guard_text_merges_pattern_and_word_density_hits_into_one_rewrite_call():
    """同一轮句式+词密度同时命中，只应发生一次 rewrite() 调用，trigger 是两个裸值用"；"拼接。"""
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=1000)
    calls = []

    async def rewrite(context, sentence, trigger):
        calls.append((sentence, trigger))
        return "他其实很在意她。"

    exhausted = []
    result = await guard_text(
        "他仿佛不是喜欢她，而是习惯了。", patterns=patterns, rewrite=rewrite,
        on_exhausted=exhausted.append, word_guard=guard,
    )
    assert result == "他其实很在意她。"
    assert len(calls) == 1  # 两类问题合并成一次调用，不是两次
    sentence, trigger = calls[0]
    assert sentence == "他仿佛不是喜欢她，而是习惯了。"
    assert trigger == "不是喜欢她，而是习惯了；仿佛"
    assert exhausted == []


@pytest.mark.asyncio
async def test_guard_text_merged_span_covers_union_of_both_sentence_boundaries():
    """句式命中句和词密度命中句不是同一句时，重写范围应扩到两者的并集（含中间无关句子）。"""
    patterns = compile_negative_patterns("- `不是【】，而是【】`")
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=1000)
    seen_offending = []

    async def rewrite(context, sentence, trigger):
        seen_offending.append(sentence)
        return sentence  # 原样放行，只关心 offending 范围本身

    text = "他仿佛愣住了。中间这句没问题。他不是喜欢她，而是习惯了。"
    await guard_text(
        text, patterns=patterns, rewrite=rewrite, on_exhausted=lambda s: None, word_guard=guard,
    )
    assert seen_offending[0] == text  # 并集覆盖了从第一句到第三句的全部文本


@pytest.mark.asyncio
async def test_guard_text_merges_multiple_simultaneous_word_density_hits_into_one_call():
    """回归用例：一句话同时踩中 3 个 threshold=0 的词时，必须一轮内全部收进同一次 rewrite()
    调用的 trigger，而不是每轮只报字典顺序最前的一个——否则 2 轮预算耗尽时，排在后面的词
    永远等不到自己的检测轮次，会跟着最后一次重写的产出被 on_exhausted 直接放行进正文。"""
    guard = WordDensityGuard(thresholds={"仿佛": 0, "似乎": 0, "骤然": 0}, window_chars=1000)
    calls = []

    async def rewrite(context, sentence, trigger):
        calls.append(trigger)
        return "他犹豫着开口。"

    exhausted = []
    result = await guard_text(
        "他仿佛骤然愣住，似乎想说什么。", patterns=[], rewrite=rewrite,
        on_exhausted=exhausted.append, word_guard=guard,
    )
    assert result == "他犹豫着开口。"
    assert len(calls) == 1  # 三个词一次性合并进同一次调用，不是分 3 轮排队
    assert calls[0] == "仿佛；似乎；骤然"  # dict 插入顺序（仿佛/似乎/骤然），不是文本内出现顺序
    assert exhausted == []
