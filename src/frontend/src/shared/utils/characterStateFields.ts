import type { StateDeriveFieldSpec } from '@/shared/types'

/** Baseline-only fallback when the API has not loaded yet (matches backend BASELINE_STATE_FIELDS). */
export const BASELINE_STATE_DERIVE_FIELDS: StateDeriveFieldSpec[] = [
  { key: 'psychology', label: '心理', kind: 'text' },
  { key: 'posture', label: '体态', kind: 'text' },
  { key: 'clothing', label: '着装', kind: 'text' },
  { key: 'action', label: '动作', kind: 'text' },
  { key: 'demeanor', label: '神态', kind: 'text' },
]

function isScoredDesc(value: unknown): value is { score: number; desc: string } {
  return (
    typeof value === 'object'
    && value !== null
    && 'desc' in value
    && typeof (value as { desc: unknown }).desc === 'string'
    && (value as { desc: string }).desc.trim() !== ''
  )
}

/** Map sandbox's loose name-keyed state dict into CharacterState[] using the active schema. */
export function toCharacterList(
  states: Record<string, Record<string, unknown>>,
  fields: StateDeriveFieldSpec[],
): import('@/shared/types').CharacterState[] {
  return Object.entries(states).map(([name, s]) => {
    const entry: import('@/shared/types').CharacterState = { name }
    for (const f of fields) {
      const v = s[f.key]
      if (f.kind === 'scored_desc' && isScoredDesc(v)) {
        const score = typeof v.score === 'number' ? v.score : Number(v.score)
        entry[f.key] = Number.isFinite(score)
          ? { score: Math.max(0, Math.min(100, Math.round(score))), desc: v.desc.trim() }
          : { score: 0, desc: v.desc.trim() }
      } else if (typeof v === 'string' && v.trim()) {
        entry[f.key] = v.trim()
      }
    }
    return entry
  })
}

export function formatStateFieldValue(
  kind: StateDeriveFieldSpec['kind'],
  value: string | { score: number; desc: string } | undefined,
): string | null {
  if (value == null || value === '') return null
  if (kind === 'scored_desc' && isScoredDesc(value)) {
    const score = typeof value.score === 'number' ? value.score : Number(value.score)
    return Number.isFinite(score) ? `${score}/100，${value.desc.trim()}` : value.desc.trim()
  }
  if (typeof value === 'string') return value.trim() || null
  return null
}
