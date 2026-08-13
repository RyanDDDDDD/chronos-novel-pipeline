import { useEffect, useMemo, useState } from 'react'
import type { LiveProfileMutation } from '@/features/sandbox/store/sandboxSlice'
import { computeFieldKeys } from '@/features/sandbox/utils/profileOverlay'

const DEFAULT_TTL_MS = 5000

/** Field keys from `mutation` that are still within `ttlMs` of its timestamp -- used to drive a
 * temporary highlight on the character card. Self-clears via a timer keyed to the exact
 * remaining time, no polling. */
export function useFreshFieldKeys(
  mutation: LiveProfileMutation | undefined, ttlMs: number = DEFAULT_TTL_MS,
): Set<string> {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!mutation) return
    const remaining = mutation.at + ttlMs - Date.now()
    if (remaining <= 0) return
    const timer = setTimeout(() => setTick((n) => n + 1), remaining)
    return () => clearTimeout(timer)
  }, [mutation, ttlMs])

  return useMemo(() => {
    if (!mutation || Date.now() - mutation.at >= ttlMs) return new Set<string>()
    return computeFieldKeys(mutation.fields)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `tick` is a deliberate recompute trigger, not a value read in the body
  }, [mutation, ttlMs, tick])
}
