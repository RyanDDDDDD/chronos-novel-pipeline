import type { CharacterArchive, RenderedSlider } from '@/shared/types'

function isSliderLevelText(v: unknown): v is { level: number; text: string } {
  return v != null && typeof v === 'object' && 'level' in v && 'text' in v
}

/** Merges one character's profile_mutate overlay fields (the shape carried by
 * story_sandbox_profile_mutation/rewrite_done WS events, matching profile_mutate.py's
 * _ALLOWED_PROFILE_FIELDS) on top of an already-rendered CharacterArchive. Mirrors
 * cast.py::_merge_profile_overlay's field semantics: sliders/physique merge per sub-key,
 * everything else replaces wholesale. Slider overlay entries arrive as raw {level,text} (same
 * shape profile_mutate.py's LLM output uses) and must be converted to the archive's already-
 * rendered {value,label} RenderedSlider shape -- the same conversion archive_view.py's
 * _render_stage_sliders performs server-side for a baseline slider. */
export function mergeSandboxProfileOverlay(
  archive: CharacterArchive, fields: Record<string, unknown>,
): CharacterArchive {
  const merged: CharacterArchive = { ...archive }
  for (const [key, val] of Object.entries(fields)) {
    if (key === 'sliders' && val && typeof val === 'object') {
      const nextSliders: Record<string, RenderedSlider> = { ...merged.sliders }
      for (const [axis, axisVal] of Object.entries(val as Record<string, unknown>)) {
        if (isSliderLevelText(axisVal)) {
          nextSliders[axis] = { value: axisVal.level, label: axisVal.text }
        }
      }
      merged.sliders = nextSliders
    } else if (key === 'physique' && val && typeof val === 'object') {
      merged.physique = { ...(merged.physique ?? {}), ...(val as Record<string, string>) }
    } else if (key === 'hobbies' && Array.isArray(val)) {
      merged.hobbies = val as string[]
    } else if (key in merged || typeof val === 'string') {
      // scalar ArchiveStage fields (personality/identity_background/verbal_tic/gender); `race`
      // is a valid profile_mutate field but archive_view.py's render_character_profile never
      // exposes it on the rendered profile (_BASE_ONLY_FIELDS) -- harmless no-op here too, since
      // CharacterCard never reads a `race` field either.
      (merged as unknown as Record<string, unknown>)[key] = val
    }
  }
  return merged
}

/** Field keys touched by one profile_mutate overlay entry, for highlight targeting: sliders/
 * physique expand to one key per axis/slot ("sliders:<axis>", "physique:<slot>"); everything
 * else is its own top-level key. */
export function computeFieldKeys(fields: Record<string, unknown>): Set<string> {
  const keys = new Set<string>()
  for (const [field, value] of Object.entries(fields)) {
    if (field === 'sliders' && value && typeof value === 'object') {
      for (const axis of Object.keys(value as Record<string, unknown>)) keys.add(`sliders:${axis}`)
    } else if (field === 'physique' && value && typeof value === 'object') {
      for (const slot of Object.keys(value as Record<string, unknown>)) keys.add(`physique:${slot}`)
    } else {
      keys.add(field)
    }
  }
  return keys
}
