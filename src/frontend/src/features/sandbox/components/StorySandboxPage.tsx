import { useEffect, useMemo, useState } from 'react'

import { useDispatch, useSelector } from 'react-redux'

import StorySandboxPanel from '@/features/sandbox/components/StorySandboxPanel'

import SandboxCharacterPanel from '@/features/sandbox/components/SandboxCharacterPanel'

import PageHeader from '@/shared/components/PageHeader'

import { useStorySandbox } from '@/features/sandbox/hooks/useStorySandbox'

import { useSandboxActiveCast } from '@/features/sandbox/hooks/useSandboxActiveCast'

import { useStorySandboxBranches } from '@/features/sandbox/queries/storySandbox'

import { readStoredBranchId, writeStoredBranchId } from '@/features/sandbox/utils/sandboxBranch'

import { useActiveNovelId } from '@/shared/queries/novels'

import { useCast, useWorld } from '@/shared/queries/setup'

import { useChapterNumbers } from '@/shared/queries/chapters'

import { selectChapter, setChapter } from '@/shared/store/uiSlice'

import type { AppDispatch } from '@/shared/store/store'

import {

  effectiveSandboxChapter,

  readStoredSandboxMode,

  writeStoredSandboxMode,

  type SandboxMode,

} from '@/features/sandbox/utils/sandboxMode'

import type { SandboxMemoryEntry } from '@/shared/types'

/** Extracts .name from each well-formed {name,desc} entry of a world_bible named-list field;
 * a not-yet-migrated legacy shape (free-text string, or string[]) contributes nothing instead
 * of throwing or leaking garbage entries. */
function namedListNames(items: unknown): string[] {
  if (!Array.isArray(items)) return []
  return items.flatMap((it) => (
    it && typeof it === 'object' && typeof (it as { name?: unknown }).name === 'string'
      ? [(it as { name: string }).name]
      : []
  ))
}

/** Independent galgame/SillyTavern-style writing sandbox: a free/chapter mode toggle (chapter

 * mode additionally picks a chapter) + one continuous chat thread per mode/chapter. Never

 * touches author_loop or plot_library. */

export default function StorySandboxPage() {

  const dispatch = useDispatch<AppDispatch>()

  const novelId = useActiveNovelId()

  const selectedChapter = useSelector(selectChapter)

  const [mode, setMode] = useState<SandboxMode>('free')

  useEffect(() => {

    if (novelId) setMode(readStoredSandboxMode(novelId))

  }, [novelId])

  const onModeChange = (next: 'chapter' | 'free') => {

    setMode(next)

    if (novelId) writeStoredSandboxMode(novelId, next)

  }

  const sandboxChapter = effectiveSandboxChapter(mode, selectedChapter)

  const chapters = useChapterNumbers(novelId, selectedChapter)

  const onSelectChapter = (ch: number) => dispatch(setChapter(ch))

  const branchesQuery = useStorySandboxBranches(novelId ?? '', sandboxChapter)

  const [branchId, setBranchId] = useState<string | null>(null)

  // Single effect, re-derived fresh from localStorage + the current query result every time --
  // never from `branchId` state, which can lag a render behind sandboxChapter on a fast chapter
  // switch (a stale-closure race previously caused this to clobber a valid stored branch with the
  // most-recent-overall fallback whenever the target chapter's branch list was already cached).
  useEffect(() => {

    if (!novelId) return

    const stored = readStoredBranchId(novelId, sandboxChapter)

    if (!branchesQuery.data) {
      // Query hasn't resolved yet for this chapter -- wait it out; the effect re-runs once
      // branchesQuery.data lands instead of guessing at a value now.
      return
    }

    const resolved = stored !== null && branchesQuery.data.some((b) => b.id === stored)
      ? stored
      : (branchesQuery.data[0]?.id ?? null)

    setBranchId(resolved)

    if (resolved !== null && resolved !== stored) writeStoredBranchId(novelId, sandboxChapter, resolved)

  }, [novelId, sandboxChapter, branchesQuery.data])

  const onBranchChange = (id: string) => {

    setBranchId(id)

    if (novelId) writeStoredBranchId(novelId, sandboxChapter, id)

  }

  const [selectedMemories, setSelectedMemories] = useState<SandboxMemoryEntry[]>([])

  const selectedMemoryIds = useMemo(
    () => new Set(selectedMemories.map((m) => m.id)), [selectedMemories],
  )

  const toggleMemory = (entry: SandboxMemoryEntry) => {

    setSelectedMemories((prev) => (
      prev.some((m) => m.id === entry.id) ? prev.filter((m) => m.id !== entry.id) : [...prev, entry]
    ))

  }

  useEffect(() => {

    setSelectedMemories([])

  }, [novelId, sandboxChapter, branchId])

  const {
    sendMessage, stopTurn, regenerateSuggestions, startRewrite, rewriteSelection, retryDerive,
    rewriteProfileMutation,
  } = useStorySandbox()

  const activeCast = useSandboxActiveCast(novelId ?? '', sandboxChapter, branchId ?? '')

  const { data: castData } = useCast()

  const characterNames = (castData ?? []).map((c) => c.name)

  const { data: worldData } = useWorld()

  const wb = worldData?.world_bible

  // Defensive against not-yet-migrated novels where these fields are still legacy shapes
  // (power_system as a free-text string, core_themes as string[]) -- Array.isArray + the
  // object/name check below make any such field contribute nothing rather than poisoning
  // settingNames with garbage entries.
  const settingNames = [
    ...namedListNames(wb?.factions),
    ...namedListNames(wb?.geography),
    ...namedListNames(wb?.races),
    ...namedListNames(wb?.power_system),
  ]



  return (

    <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-app">

      <PageHeader title="故事沙盒" subtitle="即兴写作实验：自由创作或选一章，跟 AI 一起即兴演成正文，不进正式稿。" />

      {novelId ? (

        <div className="flex-1 flex min-h-0 overflow-hidden">

          <div className="flex-1 flex flex-col min-w-0 px-4 pt-4 pb-4">

            <StorySandboxPanel

              novelId={novelId}

              mode={mode}

              onModeChange={onModeChange}

              selectedChapter={selectedChapter}

              chapters={chapters}

              onSelectChapter={onSelectChapter}

              branchId={branchId}

              onBranchChange={onBranchChange}

              sendMessage={sendMessage}

              stopTurn={stopTurn}

              regenerateSuggestions={regenerateSuggestions}

              startRewrite={startRewrite}

              rewriteSelection={rewriteSelection}

              retryDerive={retryDerive}

              rewriteProfileMutation={rewriteProfileMutation}

              characterNames={characterNames}

              settingNames={settingNames}

              selectedMemories={selectedMemories}

              onRemoveMemory={(id) => setSelectedMemories((prev) => prev.filter((m) => m.id !== id))}

              onClearMemories={() => setSelectedMemories([])}

            />

          </div>

          <SandboxCharacterPanel

            novelId={novelId}

            chapter={sandboxChapter}

            activeCast={activeCast}

            branchId={branchId}

            selectedMemoryIds={selectedMemoryIds}

            onToggleMemory={toggleMemory}

          />

        </div>

      ) : (

        <div className="flex-1 flex items-center justify-center text-sm text-slate-400">加载中…</div>

      )}

    </div>

  )

}


