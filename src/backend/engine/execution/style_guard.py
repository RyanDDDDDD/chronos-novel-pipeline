"""正文机械护栏：识别禁用句式，命中触发局部重写。

纯逻辑，不碰 LLM 客户端/WebSocket——`rewrite`/`on_exhausted` 走依赖注入，
真正的 LLM 调用与日志由调用方（message_hub.py）提供，方便离线单测。

句式模式硬编码在本文件（见 `_NEGATIVE_SENTENCE_PATTERNS`），与
`skills/prose-style-negative.md`（纯 LLM 提示文本，是否生效取决于模型是否听话）
彻底解耦：机械护栏不依赖模型配合，靠代码级正则强制重写。
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache

# 归一化句式：【】= 任意占位（不跨句号），{A|B|C} = 枚举选一。
_NEGATIVE_SENTENCE_PATTERNS: tuple[str, ...] = (
    "不是【】{，|。|——}{是|而是|只是}【】",
    "不是【】{，|。|——}{也不是|不是}【】",
    "不仅【】{，|。|——}反而【】",
    "是【】{，|。|——}而不是【】",
    "【】{，|。|——}但那已经不是【】{，|。|——}{而是|只是}【】",
    "并非【】{，|。|——}{是|而是|只是}【】",
    "并非【】{，|。|——}也并非【】",
    "明明【】{，|。|——}身体却【】",
    "虽然心中万般抗拒{，|。|——}但【】还是【】",
    "动作微微一顿{，|。|——}最终还是【】",
    "{理智|本能|恐惧|绝望}{，|。|——}像{潮水|野兽|电流|蛛网}一般{，|。|——}将她{淹没|撕扯|吞噬|包裹}",
    "最后一根理智的弦彻底崩断",
    "{像|仿佛|宛如|犹如|好似}【】{一般|一样|似的}",
    "仿佛在【】{，|。|——}又像是在【】",
    "哑得{像|像是|仿佛|宛如|犹如|好似}【】",
    "似是【】{，|。|——}又夹杂着【】",
    "不知是【】{，|。|——}还是【】",
    "这一刻{，|。|——}只剩下【】",
    "那是对【】的彻底告别",
    "宣告着她【】的{溃败|崩溃}",
    "这一次{，|。|——}他动了。",
    "空气{，|。|——}死一般的安静。",
    "节奏不快{，|。|——}但很重。",
    "愣了一下{，|。|——}然后【】",
    "——那种【】的",
    "没有【】{，|。|——}{而是|只是}【】",
    "原本【】{，|。|——}这下{全被|都被|全都被}【】",
    "{安静|沉默|停顿|平静}了{一两|两三|三两|三五}秒",
    "站在那里{，|。|——}没有动。",
    "{嘴唇|唇瓣|嘴角}动了动{，|。|——}却没{发出声音|出声}{，|。|——}像是【】",
    "深吸{了|}一口气",
    "【】顿了顿",
    "顿了顿{，|。|——}{然后|才|又|最终|还是|便}【】",
    "这{不仅|不只|不仅仅}是【】{，|。|——}{更|而}是【】",
    "无论是【】{，|、}还是【】{，|、}{都|皆|均}【】",
    "不得不说{，|。}",
    "不可否认{，|的是}",
    "毋庸置疑{，|的是}",
    "值得{一提|注意|玩味}的是",
)

# 结构类反向模式：迷你 DSL（【】/{}）不支持重复量词，单独走原生正则，
# 编译结果合并进 get_compiled_patterns() 的同一张表，复用同一套检测/重写流水线。
_STRUCTURAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 定语堆叠收尾：「X的、」连续 2 次以上再接收尾短语，如"亮晶晶的、带着期待的湿润"
    re.compile(r"(?:[^，。！？、]{1,15}的、){2,}[^，。！？、]{1,15}(?=[，。！？])"),
)

_WILDCARD_SPAN = 30
_PHRASE_GAP_SPAN = 4  # WORD_THRESHOLDS 里含【】的短语模式用这个跨度，只兜语法插字（了/几分等），不吞整个从句
_SENT_END = "。！？"
_MAX_REWRITE_ATTEMPTS = 2
_WORD_WINDOW_CHARS = 10000  # 词密度滑动窗口大小（字符数）

WORD_THRESHOLDS: dict[str, int] = {
    # 高频虚词档：窗口内允许 10-20 次
    "似乎": 20, "仿佛": 20, "更是": 18, "不仅仅是": 15,
    "骤然": 1, "猛地": 1, "细微": 1, "恍惚": 2,
    # 中频套话档：窗口内允许 1-10 次
    "下意识": 10, "一抹": 1, "破碎": 1, "瞳孔": 0, "刹那间": 7,
    "笑意": 1, "深吸": 1, "弧度": 2, "闷哼": 0, "昏黄": 1,
    "微光": 1, "涣散": 1, "拔高": 1, "沟壑": 1,"微微": 0,
    "似的": 2, "一样": 2, "压低【】声音": 0, "指节{发|泛}白": 0,
    # 生僻黑话档：出现一次即触发
    "痉挛": 1, "一绺": 1, "裂口": 1, "经络": 1, "液痕": 1,
    "翕张": 1, "浅痕": 1, "餍足": 0, "鸡皮疙瘩": 0, "弓起": 1,
    "沙哑": 0, "低哑": 0,"低沉": 0, "笑痕": 1, "慵懒": 0, "刷地": 0,
    "嘶哑": 0, "指印": 0, "翕动": 0, "绷紧": 0, "绷直": 0, "绷起": 0,
    "耳廓": 0, "闷响": 0, "闷闷": 0, "闷哑": 0, "闷沉": 0, "微哑": 0,
    "微启": 0
}


@lru_cache(maxsize=1)
def forbidden_words_text() -> str:
    """顿号连接的 WORD_THRESHOLDS 全量词表，供重写 prompt 附带展示。重写 closure 原先只把
    当轮命中的具体词塞进 prompt，LLM 看不到同族其余禁用词，容易在近义词间打转从一个禁用词
    换成另一个（如 低沉 -> 沙哑 -> 慵懒，三者都是阈值 0 的嗓音套话）——附上全表让它一次避开。"""
    return "、".join(WORD_THRESHOLDS)


_BULLET_RE = re.compile(r"^- `(.+)`\s*$", re.MULTILINE)
_TOKEN_RE = re.compile(r"(【[^】]*】|\{[^}]+\})")

Rewrite = Callable[[str, str, str], Awaitable[str]]
OnExhausted = Callable[[str], None]


@dataclass
class WordDensityGuardSnapshot:
    """Opaque point-in-time copy of a WordDensityGuard's sliding-window state, produced by
    snapshot() and consumed by restore() -- lets a caller holding a long-lived guard instance
    roll back words recorded by a since-discarded or since-replaced piece of text (a cancelled
    turn, an overwritten round) without losing the instance identity or the words recorded
    before that point."""
    chunks: list[str]
    total_len: int
    counts: dict[str, int]


class WordDensityGuard:
    """AI 特征词滑动窗口密度护栏：维护"最近文本"块列表 + 逐词计数，
    供 guarded_stream 在句式护栏之外叠加一层词汇密度检查。

    thresholds 的 key 可以是字面词（"似乎"，原样转义匹配）或含 【】 的短语模式
    （"压低【】声音"，用短跨度通配符编译，兜住"压低了声音"这类语法插字变体）——
    两种 key 在构造时统一编译成正则，之后计数/查找逻辑完全一致，无需区分。"""

    def __init__(
        self,
        thresholds: dict[str, int] | None = None,
        window_chars: int = _WORD_WINDOW_CHARS,
    ) -> None:
        self._thresholds = thresholds if thresholds is not None else WORD_THRESHOLDS
        self._window_chars = window_chars
        self._chunks: list[str] = []
        self._total_len = 0
        self._counts: dict[str, int] = dict.fromkeys(self._thresholds, 0)
        self._patterns: dict[str, re.Pattern[str]] = {
            word: _compile_density_key(word) for word in self._thresholds
        }

    def record(self, text: str) -> None:
        """把最终定稿文本计入滑动窗口，从最早的块开始裁剪超出 window_chars 的部分。"""
        if not text:
            return
        self._chunks.append(text)
        self._total_len += len(text)
        for word in self._thresholds:
            self._counts[word] += _count_matches(self._patterns[word], text)
        while self._total_len > self._window_chars and len(self._chunks) > 1:
            dropped = self._chunks.pop(0)
            self._total_len -= len(dropped)
            for word in self._thresholds:
                self._counts[word] = max(
                    self._counts[word] - _count_matches(self._patterns[word], dropped), 0
                )

    def check(self, text: str) -> list[tuple[str, int]]:
        """只读探测：返回把 text 计入窗口后**所有**超过阈值的词，各自带它在 text 内
        最后一次出现的下标（只能定位新增文本里的实例，才谈得上重写）；不提交状态。
        一次性收集全部命中而非只报第一个——同一段文本常同时踩中好几个 threshold=0 的词
        （高密度氛围词文风尤其常见），只报一个会让其余的词要等到下一轮检测才有机会被
        发现，而重写轮数有限（_MAX_REWRITE_ATTEMPTS），等不到下一轮就被 on_exhausted 放行。"""
        hits: list[tuple[str, int]] = []
        for word, limit in self._thresholds.items():
            matches = list(self._patterns[word].finditer(text))
            if not matches:
                continue
            projected = self._counts[word] + len(matches)
            if projected > limit:
                hits.append((word, matches[-1].start()))
        return hits

    def reset_word(self, word: str) -> None:
        """触发即改写后的简化"冷却"：把该词计数清零，视为预算重置。"""
        self._counts[word] = 0

    def snapshot(self) -> WordDensityGuardSnapshot:
        """Deep-copy the current sliding-window state so a caller can later restore() to this
        exact point, discarding anything recorded in between."""
        return WordDensityGuardSnapshot(list(self._chunks), self._total_len, dict(self._counts))

    def restore(self, snapshot: WordDensityGuardSnapshot) -> None:
        """In-place rollback to a previously captured snapshot() -- mutates this same instance
        (never swaps in a new object) so long-lived callers holding a reference keep seeing
        the rolled-back state."""
        self._chunks = list(snapshot.chunks)
        self._total_len = snapshot.total_len
        self._counts = dict(snapshot.counts)


def _pattern_to_regex(raw: str, wildcard_span: int = _WILDCARD_SPAN) -> re.Pattern[str]:
    """把归一化句式（【】任意占位 / {A|B} 枚举）编译成正则；其余字符按字面量转义。
    wildcard_span 控制【】允许跨多少字符——句式表用默认的整句跨度，
    WORD_THRESHOLDS 的短语 key 走 _compile_density_key 时传入更窄的 _PHRASE_GAP_SPAN。"""
    parts: list[str] = []
    for part in _TOKEN_RE.split(raw):
        if not part:
            continue
        if part.startswith("【"):
            parts.append(f"[^{_SENT_END}\\n]{{0,{wildcard_span}}}")
        elif part.startswith("{"):
            options = part[1:-1].split("|")
            parts.append("(?:" + "|".join(re.escape(o) for o in options) + ")")
        else:
            parts.append(re.escape(part))
    return re.compile("".join(parts))


def _compile_density_key(word: str) -> re.Pattern[str]:
    """WordDensityGuard 的 key 编译入口：含【】或{A|B}任一 DSL token 的短语模式走
    窄跨度通配符 DSL，普通字面词整体转义——两者编译结果都是普通 re.Pattern，
    调用方无需区分。判断用 _TOKEN_RE 而非只查【，否则纯 {A|B} 枚举（无【】间隙）
    的 key 会被误判成字面词，{} 里的字符被转义成永远不命中的死正则。"""
    if _TOKEN_RE.search(word):
        return _pattern_to_regex(word, wildcard_span=_PHRASE_GAP_SPAN)
    return re.compile(re.escape(word))


def _count_matches(pattern: re.Pattern[str], text: str) -> int:
    return sum(1 for _ in pattern.finditer(text))


def compile_negative_patterns(card_text: str) -> list[re.Pattern[str]]:
    """解析归一化反向 prompt 文本里所有 `` - `句式` `` 条目，编译成正则表。"""
    return [_pattern_to_regex(m.group(1)) for m in _BULLET_RE.finditer(card_text)]


def find_violation(text: str, patterns: list[re.Pattern[str]]) -> re.Match[str] | None:
    """返回文本里命中的第一条禁用句式；无命中 → None。"""
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m
    return None


def expand_to_sentence(text: str, span: tuple[int, int]) -> tuple[int, int]:
    """把命中 span 向左右扩到最近的句读边界（。！？或文本首尾），定位完整命中句。"""
    start, end = span
    left = start
    while left > 0 and text[left - 1] not in _SENT_END:
        left -= 1
    right = end
    while right < len(text) and text[right] not in _SENT_END:
        right += 1
    if right < len(text):
        right += 1
    return left, right


@lru_cache(maxsize=1)
def get_compiled_patterns() -> list[re.Pattern[str]]:
    """进程内只编译一次；模式来源见本文件顶部 `_NEGATIVE_SENTENCE_PATTERNS`
    （迷你 DSL）+ `_STRUCTURAL_PATTERNS`（原生正则，DSL 表达不了的重复结构）。"""
    return [_pattern_to_regex(p) for p in _NEGATIVE_SENTENCE_PATTERNS] + list(_STRUCTURAL_PATTERNS)


async def guard_text(
    text: str,
    *,
    patterns: list[re.Pattern[str]],
    rewrite: Rewrite,
    on_exhausted: OnExhausted,
    word_guard: WordDensityGuard | None = None,
    context: str = "",
) -> str:
    """单条文本的违规检测+重写：每轮同时跑句式检测和词密度检测，把命中的问题（句式最多 1 个，
    词密度当轮所有同时超标的词全收集）合并成一次 rewrite() 调用，范围取所有命中句子边界的
    并集。最多重试 _MAX_REWRITE_ATTEMPTS 轮，轮完仍有问题就不再回退，直接接受当前文本，只
    调用 on_exhausted 报警——问题共享同一个重写循环后，事后已经无法干净拆分"哪部分改动对应
    哪一类问题"，与其做残缺的部分回退，不如接受结果并留痕。最终产出的文本（不管是否清零）
    都会计入 word_guard（若传入）的滑动窗口。"""
    candidate = text
    original_sentence: str | None = None

    for _attempt in range(_MAX_REWRITE_ATTEMPTS):
        pattern_match = find_violation(candidate, patterns)
        word_hits = word_guard.check(candidate) if word_guard is not None else []
        if pattern_match is None and not word_hits:
            break

        spans: list[tuple[int, int]] = []
        triggers: list[str] = []
        if pattern_match is not None:
            spans.append(expand_to_sentence(candidate, pattern_match.span()))
            triggers.append(pattern_match.group())
        for word, idx in word_hits:
            spans.append(expand_to_sentence(candidate, (idx, idx + len(word))))
            triggers.append(word)

        left = min(span[0] for span in spans)
        right = max(span[1] for span in spans)
        trigger = triggers[0] if len(triggers) == 1 else "；".join(triggers)
        offending = candidate[left:right]
        if original_sentence is None:
            original_sentence = offending

        rewritten = await rewrite(context, offending, trigger)
        candidate = candidate[:left] + rewritten + candidate[right:]
    else:
        still_pattern = find_violation(candidate, patterns) is not None
        still_word = word_guard is not None and bool(word_guard.check(candidate))
        if still_pattern or still_word:
            on_exhausted(original_sentence if original_sentence is not None else candidate)

    if word_guard is not None:
        word_guard.record(candidate)

    return candidate


async def guarded_stream(
    token_aiter: AsyncIterator[str],
    *,
    patterns: list[re.Pattern[str]],
    rewrite: Rewrite,
    on_exhausted: OnExhausted,
    flush_every: int = 4,
    word_guard: WordDensityGuard | None = None,
) -> AsyncIterator[str]:
    """把逐 token 的流按句读切片，命中禁用句式或词密度超标就局部重写后再放行。

    每攒够 `flush_every` 个句末标点或遇到段落空行就切一段整体校验；句式命中重写最多重试
    `_MAX_REWRITE_ATTEMPTS` 次，仍命中则放行最初原句并调用 on_exhausted。句式检查结束后
    （若传了 word_guard）再对结果跑一遍词密度检查，命中复用同一套重写/重试/on_exhausted
    机制；无论是否命中，最终产出文本都会被计入 word_guard 的滑动窗口。
    """
    accepted_tail = ""

    async def _resolve(chunk: str) -> str:
        nonlocal accepted_tail
        candidate = await guard_text(
            chunk, patterns=patterns, rewrite=rewrite, on_exhausted=on_exhausted,
            word_guard=word_guard, context=accepted_tail,
        )
        accepted_tail = (accepted_tail + candidate)[-80:]
        return candidate

    buf = ""
    sent_count = 0
    async for token in token_aiter:
        buf += token
        sent_count += sum(1 for c in token if c in _SENT_END)
        if sent_count >= flush_every or "\n\n" in buf:
            yield await _resolve(buf)
            buf = ""
            sent_count = 0
    if buf:
        yield await _resolve(buf)
