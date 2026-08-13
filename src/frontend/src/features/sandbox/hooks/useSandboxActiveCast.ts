import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import type { AppDispatch } from '@/shared/store/store'
import { hydrateSandboxChat, selectSandboxActiveCast } from '@/features/sandbox/store/sandboxSlice'

/** Reads the in-scene cast roster from sandboxSlice.activeCast, seeded once per (novelId,
 * chapter, branchId) scope via hydrateSandboxChat and kept live thereafter by the slice's own
 * wsEventReceived case (story_sandbox_final/_states/_rewrite_done) -- mirrors
 * StorySandboxPanel's own hydrate call, and is a no-op once this scope is already hydrated
 * (see hydrateSandboxChat's sameScope guard), whichever of the two mounts first. */
export function useSandboxActiveCast(novelId: string, chapter: number, branchId: string): string[] {
  const dispatch = useDispatch<AppDispatch>()
  useEffect(() => {
    void dispatch(hydrateSandboxChat({ novelId, chapter, branchId }))
  }, [dispatch, novelId, chapter, branchId])
  return useSelector(selectSandboxActiveCast)
}
