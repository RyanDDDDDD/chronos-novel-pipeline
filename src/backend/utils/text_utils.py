"""LLM output text post-processing tool function."""
import re

from loguru import logger


def extract_output_prefix(system_prompt: str) -> str | None:
    """
Extract the output prefix tag from the agent system prompt (such as **[gesture expansion completed]**)."""
    m = re.search(r"\*\*【[^】]+完成】\*\*", system_prompt)
    return m.group(0) if m else None


def truncate_repetition(text: str, chunk_size: int = 150, threshold: int = 3) -> str:
    """Detect and truncate consecutively repeated passages in LLM output (native model re-reading errors).

    Detect by paragraph first, then by character block. Truncate when threshold times are repeated consecutively, retaining the first two times."""

    if not text:
        return text

    #Phase 1: paragraph-level (most common: the entire paragraph is repeated continuously)
    paragraphs = re.split(r"\n{2,}", text)
    run = 1
    for i in range(1, len(paragraphs)):
        normed = paragraphs[i].strip()
        if normed and normed == paragraphs[i - 1].strip():
            run += 1
            if run >= threshold:
                keep = i - run + 2  #Keep the first time + one repetition
                truncated = "\n\n".join(paragraphs[:keep])
                logger.warning("[repetition] 段落重复 {}×，已截断（保留 {} 段）", run, keep)
                return truncated
        else:
            run = 1

    #Phase 2: char-chunk level (recovery when paragraphs are not aligned)
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    run = 1
    for i in range(1, len(chunks)):
        if chunks[i] == chunks[i - 1]:
            run += 1
            if run >= threshold:
                keep_chars = (i - run + 2) * chunk_size
                logger.warning("[repetition] 字符块重复 {}×，已截断（保留 {} 字符）", run, keep_chars)
                return text[:keep_chars]
        else:
            run = 1

    return text


def strip_thinking(text: str, output_prefix: str | None, *, log: bool = False) -> str:
    """
Trim inference text before prefix in LLM output and remove <think>...</think> blocks.
    If the model outputs prefix (draft + final version) multiple times, take the last occurrence position."""
    if log:
        for block in re.findall(r"<think>(.*?)</think>", text, re.DOTALL):
            if block.strip():
                logger.debug("[thinking]\n{}", block.strip())
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if not output_prefix:
        return text
    idx = text.find(output_prefix)
    if idx != -1:
        if log and idx > 0:
            pre = text[:idx].strip()
            if pre:
                logger.debug("[thinking/pre-prefix]\n{}", pre)
        return text[idx:]
    return text
