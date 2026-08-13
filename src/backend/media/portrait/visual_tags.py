"""Extract an English SDXL-style tag phrase from a character's visible-appearance
fields (gender/physique/clothing_dna only -- personality is not visual). Called once
per add_character/edit_character (see engine.setup_chat.character_visual_tags), not
per portrait generation; the result is cached on the character record."""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

_SYSTEM_PROMPT = (
    "You are a prompt engineer for text-to-image models. Convert the character's visible "
    "appearance fields below into an English prompt suitable for an anime-style SDXL/FLUX "
    "model: comma-separated keyword phrases. No explanations, no Chinese, no full sentences, "
    "no quotes. "
    "Never include a specific or numeric age in the output (e.g. '17yo', '16 years old', "
    "'age: 15'), even if the source fields mention one -- age is not a visual/drawable "
    "trait and such tags risk tripping third-party image platforms' content filters. "
    "Describe body proportions and style only, with no age label of any kind. "
    "The source fields often describe this character relative to a sibling, twin, or other "
    "named character (e.g. 'softer build than her twin sister', 'bigger than her older "
    "sister') for narrative flavor -- this is a single-character portrait, not a group "
    "shot. Rewrite every such comparison into an absolute, standalone descriptor of THIS "
    "character alone (e.g. 'softer build than her twin sister' -> 'slender, delicate "
    "build'). Never name, reference, or imply a second person in the output, and never "
    "emit multi-subject tags like '2girls' or 'sisters' -- the output must describe "
    "exactly one person."
)


def _describe_character_visual(character: dict) -> str:
    lines = [
        f"gender: {character.get('gender') or ''}",
        f"physique: {character.get('physique') or {}}",
        f"clothing: {character.get('clothing_dna') or {}}",
    ]
    return "\n".join(lines)


async def extract_visual_tags(character: dict) -> str:
    from context.content_packs import active_portrait_directive
    from llm.factory import get_cloud_llm

    llm = get_cloud_llm()
    system_text = _SYSTEM_PROMPT
    directive = active_portrait_directive()
    if directive:
        system_text = f"{system_text}\n\n{directive}"

    user = _describe_character_visual(character)
    resp = await llm.ainvoke([SystemMessage(content=system_text), HumanMessage(content=user)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return text.strip()


async def extract_and_persist_visual_tags(novel_id: str, name: str, character: dict) -> str:
    from repositories import get_lore_repo
    from utils.paths import use_novel

    tags = await extract_visual_tags(character)
    with use_novel(novel_id):
        repo = get_lore_repo()
        roster = repo.list_raw()
        for c in roster:
            if isinstance(c, dict) and c.get("name") == name:
                c["portrait_visual_tags"] = tags
                break
        repo.save_all(roster)
    return tags
