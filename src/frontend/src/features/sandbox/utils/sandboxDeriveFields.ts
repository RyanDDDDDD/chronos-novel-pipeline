import type { TurnFilterCat } from '@/features/sandbox/components/StorySandboxSegments'

/** Registry of sandbox fields that may show a post-prose derivation loading row. */
export const SANDBOX_DERIVE_FIELDS = {
  initialStates: {
    label: '正在推导角色进入态…',
    filterCat: 'state' as TurnFilterCat,
    variant: 'state' as const,
  },
  initialSceneState: {
    label: '正在推导场景进入态…',
    filterCat: 'state' as TurnFilterCat,
    variant: 'state' as const,
  },
  characterStates: {
    label: '正在推演角色状态…',
    filterCat: 'state' as TurnFilterCat,
    variant: 'state' as const,
  },
  sceneState: {
    label: '正在推演场景状态…',
    filterCat: 'state' as TurnFilterCat,
    variant: 'state' as const,
  },
  suggestions: {
    label: '正在推演剧情走向…',
    filterCat: 'suggestions' as TurnFilterCat,
    variant: 'suggestions' as const,
  },
} as const

export type SandboxDeriveField = keyof typeof SANDBOX_DERIVE_FIELDS

export type PendingDerivations = Partial<Record<SandboxDeriveField, boolean>>

export function isSandboxDeriveField(value: string): value is SandboxDeriveField {
  return value in SANDBOX_DERIVE_FIELDS
}

export function markDerivationsPending(
  prev: PendingDerivations,
  fields: readonly string[],
): PendingDerivations {
  let next = prev
  for (const field of fields) {
    if (!isSandboxDeriveField(field)) continue
    if (next[field]) continue
    next = { ...next, [field]: true }
  }
  return next
}

export function clearDerivationPending(
  prev: PendingDerivations,
  field: SandboxDeriveField,
): PendingDerivations {
  if (!prev[field]) return prev
  const next = { ...prev }
  delete next[field]
  return next
}

export function clearAllDerivationsPending(): PendingDerivations {
  return {}
}
