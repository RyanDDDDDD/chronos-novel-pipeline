"""Extract an English SDXL-style tag phrase from a character's visible-appearance
fields (gender/physique/clothing_dna only -- personality is not visual). Called once
per add_character/edit_character (see engine.setup_chat.character_visual_tags), not
per portrait generation; the result is cached on the character record."""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

_SYSTEM_PROMPT = (
    "You are a prompt engineer for text-to-image models. Convert the character's visible "
    "appearance fields below into an English SDXL/FLUX-style prompt: comma-separated keyword "
    "phrases. No explanations, no Chinese, no full sentences, no quotes. "
    "Never include an art style, medium, or rendering technique tag of any kind (examples to "
    "avoid: 'anime style', 'manga', 'realistic', 'photorealistic', '3d render', 'oil painting', "
    "'watercolor', 'comic style', 'semi-realistic'). Art style is chosen by a separate, "
    "independent layer downstream and must never be baked into this output -- describe only "
    "physical appearance, body proportions, and clothing/accessories (pure visual facts), "
    "never the rendering style they should be drawn in. "
    "Never include a specific or numeric age in the output (e.g. '17yo', '16 years old', "
    "'age: 15'), even if the source fields mention one -- age is not a visual/drawable "
    "trait and such tags risk tripping third-party image platforms' content filters. "
    "Describe body proportions only, with no age label of any kind. "
    "The source fields often describe this character relative to a sibling, twin, or other "
    "named character (e.g. 'softer build than her twin sister', 'bigger than her older "
    "sister') for narrative flavor -- this is a single-character portrait, not a group "
    "shot. Rewrite every such comparison into an absolute, standalone descriptor of THIS "
    "character alone (e.g. 'softer build than her twin sister' -> 'slender, delicate "
    "build'). Never name, reference, or imply a second person in the output, and never "
    "emit multi-subject tags like '2girls' or 'sisters' -- the output must describe "
    "exactly one person.\n\n"
    "If a non-empty 'franchise' is given AND you confidently recognize 'name' as a specific "
    "character from that work, BEGIN the output with their danbooru tags: 'character name "
    "(series), series' (for example 'shiroko (blue archive), blue archive'), then a comma, "
    "then the appearance tags. Only do this for well-known characters you are sure about. "
    "If 'franchise' is empty, or you are not certain which character this is, emit NO "
    "identity/series tag at all and just describe appearance as usual.\n"
    "EXCEPTION: if the source fields contain a line 'identity_anchor_provided: yes', an "
    "external identity anchor is already set -- in that case never emit any character-name "
    "or series tag yourself, only appearance tags.\n\n"
    "Match the shape of this example (format only -- do not reuse its wording unless it "
    "genuinely matches the source fields):\n"
    "female, solo, tall slender build, fair skin, long wavy chestnut hair, sharp amber eyes, "
    "delicate oval face, calm composed expression, fitted navy trench coat, leather gloves, "
    "knee-high boots, silver chain necklace"
)


def _describe_character_visual(character: dict, *, franchise: str = "") -> str:
    lines = [
        f"name: {character.get('given_name') or character.get('name') or ''}",
        f"franchise: {franchise}",
        f"gender: {character.get('gender') or ''}",
        f"physique: {character.get('physique') or {}}",
        f"clothing: {character.get('clothing_dna') or {}}",
    ]
    return "\n".join(lines)


async def extract_visual_tags(character: dict, *, franchise: str = "") -> str:
    from context.content_packs import active_portrait_directive
    from llm.factory import get_cloud_llm

    llm = get_cloud_llm()
    system_text = _SYSTEM_PROMPT
    directive = active_portrait_directive()
    if directive:
        system_text = f"{system_text}\n\n{directive}"

    user = _describe_character_visual(character, franchise=franchise)
    if (character.get("portrait_identity_tags") or "").strip():
        # A manual anchor is authoritative -- tell the LLM not to also derive one.
        user = f"{user}\nidentity_anchor_provided: yes"
    resp = await llm.ainvoke([SystemMessage(content=system_text), HumanMessage(content=user)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return text.strip()


async def extract_and_persist_visual_tags(novel_id: str, name: str, character: dict) -> str:
    from repositories import get_lore_repo
    from utils.paths import use_novel

    with use_novel(novel_id):
        from api.services.novels import get_source_franchise

        franchise = get_source_franchise(novel_id)
    tags = await extract_visual_tags(character, franchise=franchise)
    with use_novel(novel_id):
        repo = get_lore_repo()
        roster = repo.list_raw()
        for c in roster:
            if isinstance(c, dict) and c.get("name") == name:
                c["portrait_visual_tags"] = tags
                break
        repo.save_all(roster)
    return tags
