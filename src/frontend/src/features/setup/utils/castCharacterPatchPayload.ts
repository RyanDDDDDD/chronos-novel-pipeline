import type { CastCharacter, CastCharacterInput, CustomFieldSpec } from '@/shared/types'
import type { ParsedCastCharacterMarkdown } from '@/features/setup/utils/parseCastCharacterMarkdown'

export function buildCastCharacterPatchPayload(
  baseline: CastCharacter,
  parsed: ParsedCastCharacterMarkdown,
  customFieldSpecs: CustomFieldSpec[],
): CastCharacterInput {
  const clothing = {
    ...baseline.clothing_dna,
    ...parsed.clothing_dna,
  }

  const payload: CastCharacterInput = {
    given_name: parsed.given_name ?? baseline.given_name ?? baseline.name,
    role: parsed.role ?? baseline.role ?? '',
    gender: parsed.gender ?? baseline.gender ?? '',
    causal_anchors: parsed.causal_anchors ?? baseline.causal_anchors ?? {},
    physique: parsed.physique ?? baseline.physique ?? {},
    clothing_color_palette: clothing.color_palette ?? [],
    clothing_materials: clothing.materials_preference ?? [],
    clothing_signature_outfit: clothing.signature_outfit ?? '',
    clothing_accessories: clothing.accessories ?? [],
    sliders: baseline.sliders ?? {},
    personality: parsed.personality ?? baseline.personality ?? '',
    race: parsed.race ?? baseline.race ?? '',
    identity_background: parsed.identity_background ?? baseline.identity_background ?? '',
    hobbies: parsed.hobbies ?? baseline.hobbies ?? [],
    verbal_tic: parsed.verbal_tic ?? baseline.verbal_tic ?? '',
    portrait_visual_tags: parsed.portrait_visual_tags ?? baseline.portrait_visual_tags ?? '',
  }

  for (const spec of customFieldSpecs) {
    payload[spec.name] = parsed.customFields?.[spec.name]
      ?? String((baseline as unknown as Record<string, unknown>)[spec.name] ?? '')
  }

  return payload
}
