import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useWsClient } from '@/shared/hooks/useWsClient'
import { selectConnected } from '@/shared/store/connectionSlice'
import ChatComposerBar from '@/shared/components/ChatComposerBar'
import { useComposerHistory } from '@/shared/hooks/useComposerHistory'
import ChatScrollToBottomButton from '@/shared/components/ChatScrollToBottomButton'
import ChatScrollToTopButton from '@/shared/components/ChatScrollToTopButton'
import { useToast } from '@/shared/hooks/useToast'
import { useQueryClient } from '@tanstack/react-query'
import ChatHistorySyncOverlay, { CHAT_HISTORY_SYNC_LABEL } from '@/shared/components/ChatHistorySyncOverlay'
import { Button } from '@/shared/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import {
  useCreateStorySandboxBranch, useDeleteStorySandboxBranch, useRenameStorySandboxBranch,
  useResetStorySandboxBranch, useStorySandboxBranches,
} from '@/features/sandbox/queries/storySandbox'
import { useChapterSkeleton } from '@/features/setup/queries/skeleton'
import { useStateDeriveFields } from '@/shared/queries/stateDeriveFields'
import type { StorySandboxEvent } from '@/features/sandbox/utils/storySandboxHistory'
import { useChatScrollFollow } from '@/shared/hooks/useChatScrollFollow'
import {
  TurnSegments, TURN_FILTER_CATS, InitialContextCard, SelectedDirectionsCard, SelectedMemoriesCard,
  type TurnFilterCat,
} from '@/features/sandbox/components/StorySandboxSegments'
import StorySandboxBranchModal from '@/features/sandbox/components/StorySandboxBranchModal'
import StorySandboxBranchMenu from '@/features/sandbox/components/StorySandboxBranchMenu'
import { formatRecalledMemoryLine } from '@/features/sandbox/utils/sandboxMemorySearch'
import { fetchSceneImages, requestSceneImage } from '@/features/sandbox/queries/sceneImage'
import { effectiveSandboxChapter, type SandboxMode } from '@/features/sandbox/utils/sandboxMode'
import { detectRecognizedNames, type MentionCandidate } from '@/shared/components/mention/mentionCandidates'
import type { Round } from '@/features/sandbox/hooks/useStorySandbox'
import type { AppDispatch } from '@/shared/store/store'
import type { SandboxMemoryEntry } from '@/shared/types'
import {
  hydrateSandboxChat, selectSandboxChat, selectSandboxHydrating, selectSandboxHydratedScope,
  selectSandboxHydrateEpoch,
  sandboxChatTurnSubmitted, sandboxChatReset,
  sandboxChatEventApplied, sandboxChatRewriteStarted, sandboxChatRegenerateStarted,
  sandboxChatProfileMutationRewriteStarted,
  sandboxChatSelectionRewriteFired, sandboxChatSelectionRewriteQueued,
} from '@/features/sandbox/store/sandboxSlice'
import { isSandboxComposerBusy } from '@/features/sandbox/utils/sandboxChatState'

export type { SandboxMode } from '@/features/sandbox/utils/sandboxMode'

function storySandboxDraftKey(novelId: string, chapter: number): string {
  return `story-sandbox-draft:${novelId}:${chapter}`
}

/** Marks that this chapter's opening turn has already been sent at least once, independent of
 * the draft key -- the draft-persist effect always writes the current (possibly empty) input
 * back to sessionStorage on every mount, including the very first one, so an empty draft alone
 * can't tell "genuinely fresh, nothing sent yet" apart from "already submitted, composer
 * cleared". This key is only ever written by submit() itself, so it survives a remount (e.g.
 * switching to another tab and back) without being clobbered by that unrelated effect. */
function storySandboxOpeningSentKey(novelId: string, chapter: number): string {
  return `story-sandbox-opening-sent:${novelId}:${chapter}`
}

function hashString32(s: string): string {
  // Stable, fast enough for UI keys; avoids index-based keys that can cause DOM reuse glitches.
  let h = 5381
  for (let i = 0; i < s.length; i += 1) {
    h = ((h << 5) + h) ^ s.charCodeAt(i)
  }
  return (h >>> 0).toString(16)
}

function stableRoundKey(r: Round): string {
  const sig = [
    r.instruction ?? '',
    r.prose ?? '',
    (r.suggestions ?? []).join('\n'),
    // initialStates/characterStates ordering can differ across serializations; they should not
    // affect identity for rendering order stability.
  ].join('\n---\n')
  return `r_${hashString32(sig)}`
}

/** Single source of truth for "what text a turn submit actually sends" — shared by submit()
 * itself and the composer's recognized-names/settings preview, so a selected-but-not-retyped
 * direction pill is scanned the same way it's transmitted. */
export function buildSubmissionText(
  input: string, selectedDirections: string[], selectedMemoryLines: string[] = [],
): string {
  const parts: string[] = []
  if (selectedDirections.length > 0) {
    parts.push(selectedDirections.map((d) => `- ${d}`).join('\n'))
  }
  if (selectedMemoryLines.length > 0) {
    parts.push(selectedMemoryLines.join('\n'))
  }
  if (input.trim()) parts.push(input.trim())
  return parts.join('\n\n')
}

interface Props {
  novelId: string
  mode: SandboxMode
  onModeChange: (mode: 'chapter' | 'free') => void
  selectedChapter: number
  chapters: number[]
  onSelectChapter: (chapter: number) => void
  branchId: string | null
  onBranchChange: (id: string) => void
  sendMessage: (chapter: number, branchId: string, text: string, submittedDirections?: string[]) => Promise<{ ok: boolean; error?: string }>
  stopTurn: (chapter: number, branchId: string) => Promise<{ ok: boolean; error?: string }>
  regenerateSuggestions: (chapter: number, branchId: string, hint?: string) => Promise<{ ok: boolean; error?: string }>
  startRewrite: (chapter: number, branchId: string, feedback: string) => Promise<{ ok: boolean; error?: string }>
  rewriteSelection: (
    chapter: number, branchId: string, originalText: string, anchorOffset: number, feedback: string,
    roundId?: string,
  ) => Promise<{ ok: boolean; error?: string }>
  retryDerive: (chapter: number, branchId: string) => Promise<{ ok: boolean; error?: string }>
  rewriteProfileMutation: (chapter: number, branchId: string, feedback: string) => Promise<{ ok: boolean; error?: string }>
  /** 全量角色名单（@ 提示候选 + "识别到角色" 提示行的来源）；未传视为空。 */
  characterNames?: string[]
  /** 全量设定名单（factions/geography/races/power_system 具名条目的 name 拉平合并，不含
   * core_themes；@ 提示候选 + "识别到设定" 提示行的来源）；未传视为空。 */
  settingNames?: string[]
  /** 手动召回的归档记忆，纯前端状态（由 StorySandboxPage 提升持有），提交时格式化拼进发送文本。 */
  selectedMemories?: SandboxMemoryEntry[]
  onRemoveMemory?: (id: string) => void
  onClearMemories?: () => void
}

export default function StorySandboxPanel({
  novelId, mode, onModeChange, selectedChapter, chapters, onSelectChapter,
  branchId, onBranchChange,
  sendMessage, stopTurn, regenerateSuggestions, startRewrite, rewriteSelection, retryDerive,
  rewriteProfileMutation,
  characterNames = [], settingNames = [],
  selectedMemories = [], onRemoveMemory = () => {}, onClearMemories = () => {},
}: Props) {
  const chapter = effectiveSandboxChapter(mode, selectedChapter)

  const dispatch = useDispatch<AppDispatch>()
  const ws = useWsClient()
  const connected = useSelector(selectConnected)
  const queryClient = useQueryClient()
  const state = useSelector(selectSandboxChat)
  const historyEntries = useMemo(
    () => state.rounds.map((r) => r.instruction).filter((s) => s.length > 0),
    [state.rounds],
  )
  const composerHistory = useComposerHistory(historyEntries)
  const isSyncing = useSelector(selectSandboxHydrating)
  const hydratedScope = useSelector(selectSandboxHydratedScope)
  const hydrateEpoch = useSelector(selectSandboxHydrateEpoch)
  const [input, setInput] = useState(
    () => sessionStorage.getItem(storySandboxDraftKey(novelId, chapter)) ?? '',
  )
  const pendingTextRef = useRef('')
  const [cancelling, setCancelling] = useState(false)
  const { confirm, error: toastError, success: toastSuccess } = useToast()
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const [selectedDirections, setSelectedDirections] = useState<string[]>([])
  const [branchModalMode, setBranchModalMode] = useState<'create' | 'rename' | null>(null)
  const [hiddenCats, setHiddenCats] = useState<Set<TurnFilterCat>>(new Set())
  // roundId -> scene-image URL, fetched once per scope + refreshed on the WS done event. Kept
  // out of Redux's turn state on purpose (it's a separate sidecar doc server-side).
  const [sceneImages, setSceneImages] = useState<Record<string, string>>({})
  const [expandAll, setExpandAll] = useState<boolean | undefined>(undefined)
  const scopeKeyRef = useRef(`${novelId}:${chapter}:${branchId ?? ''}`)
  // Set right before onModeChange() so the next scope-switch effect run (chapter/free toggle
  // always changes `chapter` between 0 and selectedChapter) starts the composer blank instead of
  // restoring that scope's leftover draft -- the restore path exists for tab-switch/reload
  // recovery, not for a manual mode toggle, which should always read as a fresh start.
  const suppressDraftRestoreRef = useRef(false)
  const { data: branchList } = useStorySandboxBranches(novelId, chapter)
  const { fields: stateDeriveFields } = useStateDeriveFields()
  const createBranch = useCreateStorySandboxBranch(novelId, chapter)
  const renameBranch = useRenameStorySandboxBranch(novelId, chapter)
  const deleteBranch = useDeleteStorySandboxBranch(novelId, chapter)
  const resetBranch = useResetStorySandboxBranch(novelId, chapter)
  const { data: chapterSkeleton, isLoading: isSkeletonLoading } = useChapterSkeleton(
    mode === 'chapter' ? chapter : null,
  )
  const busy = isSandboxComposerBusy(state)
  const inputDisabled = !connected || busy || isSyncing
  const handleModeChange = (next: 'chapter' | 'free') => {
    suppressDraftRestoreRef.current = true
    onModeChange(next)
  }

  const scrollTrigger = [
    state.rounds.length,
    state.liveRound?.prose.length ?? 0,
    state.rewritingProse?.length ?? 0,
    state.status,
  ].join('|')
  const {
    scrollRef, handleScroll, showScrollToBottom, hasNewContentBelow, scrollToBottom,
    showScrollToTop, scrollToTop,
  } = useChatScrollFollow(scrollTrigger, chapter)

  // Redux (sandboxSlice.chat) is never destroyed on unmount -- a story_sandbox_* WS event keeps
  // being folded into it via wsMiddleware/wsEventReceived regardless of what's mounted. This
  // hydrate call is a no-op (see hydrateSandboxChat's sameScope guard) once this scope has
  // already been fetched once, so a remount (e.g. switching to another tab and back) never loses
  // an in-flight turn's loading animation or the user's own instruction bubble to a stale REST
  // snapshot the way the old react-query-backed restore could.
  useEffect(() => {
    if (!branchId) return
    void dispatch(hydrateSandboxChat({ novelId, chapter, branchId }))
  }, [dispatch, novelId, chapter, branchId, hydrateEpoch])

  // Set whenever the scope-switch effect below calls setInput() (restore or clear), so the
  // persist effect's very next run -- which fires in the SAME commit whenever novelId/chapter
  // also changed, and therefore still closes over the PRE-restore `input` value since its own
  // setInput() update hasn't landed yet -- skips writing that stale value back over what was
  // just restored. Without this, switching novels while `branchId` settles in two steps (the
  // parent inherits the previous novel's branchId for one render, then resolves the new
  // novel's real one on a later render -- see StorySandboxPage's branch-resolution effect)
  // reliably clobbered the just-restored draft: scope-switch effect restores "A的草稿", but the
  // persist effect (declared after it, same commit, deps also include novelId/chapter) still
  // sees the OLD (pre-restore) `input` closure and immediately writes '' back over it.
  const restoringRef = useRef(false)

  useEffect(() => {
    const scopeSwitched = scopeKeyRef.current !== `${novelId}:${chapter}:${branchId ?? ''}`
    scopeKeyRef.current = `${novelId}:${chapter}:${branchId ?? ''}`
    if (scopeSwitched) {
      restoringRef.current = true
      if (suppressDraftRestoreRef.current) {
        suppressDraftRestoreRef.current = false
        setInput('')
        try {
          sessionStorage.removeItem(storySandboxDraftKey(novelId, chapter))
        } catch {
          /*sessionStorage full/disabled -- draft persistence is a UX optimization, not load-bearing*/
        }
      } else {
        setInput(sessionStorage.getItem(storySandboxDraftKey(novelId, chapter)) ?? '')
      }
    }
  }, [novelId, chapter, branchId])

  useEffect(() => {
    if (restoringRef.current) {
      // This run's `input` is the pre-restore value from before the scope-switch effect above
      // (same commit) called setInput() -- writing it now would immediately overwrite what it
      // just restored/cleared. The next run (once `input` actually updates) persists for real.
      restoringRef.current = false
      return
    }
    try {
      sessionStorage.setItem(storySandboxDraftKey(novelId, chapter), input)
    } catch {
      /*sessionStorage full/disabled -- draft persistence is a UX optimization, not load-bearing*/
    }
  }, [novelId, chapter, input])

  // Chapter mode's opening turn used to have stage1's outline silently grounding the model via a
  // hidden system-prompt block the user never saw (removed server-side -- see
  // docs/superpowers/specs/2026-07-24-sandbox-chapter-mode-outline-prefill-design.md). This
  // effect makes that same text visible and editable instead: on a fresh chapter (no rounds yet,
  // no draft saved) it pre-fills the composer so the user's own send is what actually carries it.
  useEffect(() => {
    if (mode !== 'chapter' || isSyncing || isSkeletonLoading) return
    // `isSyncing` (sandboxSlice.hydrating) is NOT a reliable "this scope's data is confirmed
    // settled" signal on its own: resetSandbox() (dispatched synchronously by App.tsx's novel-
    // switch effect, see resetForNovelSwitch) sets hydrating back to false as part of its reset
    // baseline, and nothing flips it to true again until hydrateSandboxChat's own
    // sandboxChatHydrateBegin dispatch lands a moment later -- a real window where `isSyncing`
    // reads false and `state.rounds` reads [] even though this exact scope's real (non-empty)
    // history hasn't been fetched yet. Only trust "rounds.length === 0 means genuinely no
    // history" once hydratedScope actually matches the scope we're looking at right now.
    const scopeConfirmed = (
      hydratedScope !== null && hydratedScope.novelId === novelId
      && hydratedScope.chapter === chapter && hydratedScope.branchId === branchId
    )
    if (!scopeConfirmed) return
    if (state.rounds.length > 0) return
    // A refresh mid-generation reconnects to the in-flight opening turn via Redux's liveRound
    // (seeded by hydrateSandboxChat) before it's persisted into `rounds` -- without this check,
    // state.rounds.length still reads 0 and every refresh during that window re-clobbers the
    // composer with the outline even though the turn the user already sent is actively running.
    if (state.liveRound !== null) return
    // Belt-and-suspenders against a remount (e.g. switching to another tab and back) racing
    // ahead of the liveRound check above: sessionStorage's opening-sent marker is written
    // synchronously by submit() itself, so it's already durable even in the window where the
    // hydrate thunk hasn't resolved yet.
    if (sessionStorage.getItem(storySandboxOpeningSentKey(novelId, chapter))) return
    if (sessionStorage.getItem(storySandboxDraftKey(novelId, chapter))) return
    const stage1 = chapterSkeleton?.stages.find((s) => s.stage_num === 1)
    const stage1Description = stage1?.description.trim()
    if (!stage1Description) return
    const stage1Location = (stage1?.location ?? '').trim()
    setInput(`地点：${stage1Location}\n\n剧情：${stage1Description}`)
    toastSuccess('已自动填入本章 stage1 大纲，可编辑后发送')
  }, [
    mode, novelId, chapter, branchId, isSyncing, isSkeletonLoading, hydratedScope,
    state.rounds.length, state.liveRound !== null, chapterSkeleton, toastSuccess,
  ])

  // Redux's wsEventReceived case already folds every story_sandbox_* event into chat/activeCast
  // regardless of mount state -- this listener only handles side effects that aren't pure state
  // folding (react-query cache invalidation for the unrelated cast-archives feature, toasts, and
  // restoring the composer's text on a cancelled turn).
  useEffect(() => {
    if (!ws) return
    const onMsg = (event: MessageEvent) => {
      let ev: StorySandboxEvent | null = null
      try {
        const parsed = JSON.parse(event.data)
        if (typeof parsed?.type === 'string' && parsed.type.startsWith('story_sandbox_')) {
          ev = parsed as StorySandboxEvent
        }
      } catch {
        return
      }
      if (ev) {
        if (
          ev.type === 'story_sandbox_profile_mutation'
          || ev.type === 'story_sandbox_done'
          || ev.type === 'story_sandbox_rewrite_done'
        ) {
          void queryClient.invalidateQueries({ queryKey: ['sandboxCastArchives', novelId, chapter] })
          void queryClient.invalidateQueries({ queryKey: ['sandboxRelatedCastArchives', novelId, chapter] })
        }
        if (ev.type === 'story_sandbox_done' || ev.type === 'story_sandbox_rewrite_done') {
          // A finished (or rewritten) turn's event_log node may have appended/replaced a memory
          // entry -- refetch so the 归档记忆 panel doesn't keep showing a stale list until the
          // user happens to trigger some unrelated invalidation (e.g. resetting the branch).
          void queryClient.invalidateQueries({ queryKey: ['sandbox-memory-archive', novelId, chapter] })
        }
        if (ev.type === 'story_sandbox_turn_cancelled') {
          setInput(pendingTextRef.current)
          if (ev.rollback_failed) toastError('状态可能未完全回滚，建议刷新核实')
        }
        if (ev.type === 'story_sandbox_suggestions_regenerate_error') {
          toastError(ev.error)
        }
        if (ev.type === 'story_sandbox_selection_rewrite_error') {
          toastError(ev.error)
        }
      }
    }
    ws.addEventListener('message', onMsg)
    return () => ws.removeEventListener('message', onMsg)
  }, [ws, queryClient, novelId, chapter, branchId, toastError])

  // Scene images: fetch the whole map once per scope, then keep it fresh off the WS done event
  // (a plain listener, separate from the story_sandbox_* handler above which ignores other types).
  useEffect(() => {
    let cancelled = false
    const load = branchId
      ? fetchSceneImages(chapter, branchId)
      : Promise.resolve<Record<string, string>>({})
    void load.then((map) => { if (!cancelled) setSceneImages(map) })
    return () => { cancelled = true }
  }, [chapter, branchId, novelId])

  useEffect(() => {
    if (!ws || !branchId) return
    const onMsg = (event: MessageEvent) => {
      let parsed: { type?: string; error?: string }
      try {
        parsed = JSON.parse(event.data)
      } catch {
        return
      }
      if (parsed?.type === 'sandbox_scene_image_done' && !parsed.error) {
        void fetchSceneImages(chapter, branchId).then(setSceneImages)
      }
    }
    ws.addEventListener('message', onMsg)
    return () => ws.removeEventListener('message', onMsg)
  }, [ws, chapter, branchId])

  const handleGenerateSceneImage = (roundId: string): void => {
    if (!branchId) return
    void requestSceneImage(chapter, branchId, roundId).then((res) => {
      if (!res.ok) toastError('场景生图请求失败，请重试')
    })
  }

  const toggleDirection = (text: string) => {
    setSelectedDirections((prev) => (
      prev.includes(text) ? prev.filter((t) => t !== text) : [...prev, text]
    ))
    // Picking a direction pill is almost always followed by Enter (or a quick edit then Enter) --
    // move focus to the composer so that's a single keystroke, cursor at the end of any text
    // already typed so Enter doesn't land mid-sentence.
    const el = composerRef.current
    if (el) {
      el.focus()
      const end = el.value.length
      el.setSelectionRange(end, end)
    }
  }

  // A chapter/mode scope with no branches yet (fresh chapter, or free mode before its first
  // ever message) has branchId === null -- the page only resolves it from an already-existing
  // branch list, it never creates one speculatively. The first send in that scope is what
  // actually creates the branch, so the composer doesn't need an extra "start a story line"
  // step before it can be used.
  const resolveBranchId = async (): Promise<string | null> => {
    if (branchId) return branchId
    try {
      const created = await createBranch.mutateAsync(undefined)
      onBranchChange(created.id)
      return created.id
    } catch {
      toastError('新建故事线失败，请重试')
      return null
    }
  }

  const submit = async () => {
    const submitted = [...selectedDirections]
    const memoryLines = selectedMemories.map(formatRecalledMemoryLine)
    const text = buildSubmissionText(input, submitted, memoryLines)
    if (!text || busy || isSyncing) return
    const isOpeningTurn = state.rounds.length === 0
    if (isOpeningTurn) {
      try {
        sessionStorage.setItem(storySandboxOpeningSentKey(novelId, chapter), '1')
      } catch {
        /*sessionStorage full/disabled -- this is only a remount-race guard, not load-bearing*/
      }
    }
    // Optimistic UI update (lock pills, clear composer, show "thinking") happens synchronously,
    // same as before branches existed -- resolveBranchId only gates the actual network call
    // below, so the vast majority of sends (branchId already resolved) don't introduce a visible
    // extra tick before the composer reacts.
    dispatch(sandboxChatTurnSubmitted({
      instruction: text,
      isOpeningTurn,
      submittedDirections: submitted,
    }))
    pendingTextRef.current = text
    setInput('')
    setSelectedDirections([])
    onClearMemories()
    const activeBranchId = await resolveBranchId()
    if (!activeBranchId) {
      dispatch(sandboxChatEventApplied({ type: 'story_sandbox_error', error: '新建故事线失败，请重试' }))
      return
    }
    const res = await sendMessage(chapter, activeBranchId, text, submitted)
    if (!res.ok) {
      dispatch(sandboxChatEventApplied({ type: 'story_sandbox_error', error: res.error ?? '发送失败' }))
    }
  }

  const cancelTurn = async () => {
    setCancelling(true)
    const res = await stopTurn(chapter, branchId ?? '')
    setCancelling(false)
    if (!res.ok) {
      toastError(res.error ?? '中断失败，请重试')
      return
    }
    // story_sandbox_turn_cancelled WS event (handled above) does the state cleanup + input
    // restore -- this branch only surfaces a network-level failure.
  }

  const handleResetBranch = async () => {
    if (busy || isSyncing || !branchId) return
    if (!(await confirm('重置这条故事线，会清空所有内容但保留故事线名称，无法恢复，确定继续吗？'))) return
    try {
      await resetBranch.mutateAsync(branchId)
      dispatch(sandboxChatReset())
      setSelectedDirections([])
      onClearMemories()
      sessionStorage.removeItem(storySandboxOpeningSentKey(novelId, chapter))
      void queryClient.invalidateQueries({ queryKey: ['sandboxCastArchives', novelId, chapter] })
      void queryClient.invalidateQueries({ queryKey: ['sandboxRelatedCastArchives', novelId, chapter] })
      void queryClient.invalidateQueries({ queryKey: ['sandbox-memory-archive', novelId, chapter] })
    } catch (err) {
      dispatch(sandboxChatEventApplied({
        type: 'story_sandbox_error', error: err instanceof Error ? err.message : '重置失败',
      }))
    }
  }

  const handleDeleteBranch = async () => {
    if (busy || isSyncing || !branchId) return
    if (!(await confirm('删除这条故事线，无法恢复，确定继续吗？'))) return
    try {
      const next = await deleteBranch.mutateAsync(branchId)
      dispatch(sandboxChatReset())
      setSelectedDirections([])
      onClearMemories()
      sessionStorage.removeItem(storySandboxOpeningSentKey(novelId, chapter))
      void queryClient.invalidateQueries({ queryKey: ['sandboxCastArchives', novelId, chapter] })
      void queryClient.invalidateQueries({ queryKey: ['sandboxRelatedCastArchives', novelId, chapter] })
      void queryClient.invalidateQueries({ queryKey: ['sandbox-memory-archive', novelId, chapter] })
      onBranchChange(next.id)
    } catch (err) {
      dispatch(sandboxChatEventApplied({
        type: 'story_sandbox_error', error: err instanceof Error ? err.message : '删除失败',
      }))
    }
  }

  const handleRegenerate = (hint: string): void => {
    dispatch(sandboxChatRegenerateStarted())
    void regenerateSuggestions(chapter, branchId ?? '', hint).then((res) => {
      if (!res.ok) {
        dispatch(sandboxChatEventApplied({
          type: 'story_sandbox_suggestions_regenerate_error', error: res.error ?? '重新生成失败',
        }))
        toastError(res.error ?? '重新生成失败')
      }
    })
  }

  const handleRewrite = async (feedback: string) => {
    if (busy || isSyncing) return
    // Rewrite's prose isn't broadcast as its own event (it arrives bundled with
    // story_sandbox_rewrite_done), so there's no "final" event to key off of -- mark every
    // downstream derivation (state through suggestions) pending as soon as the rewrite starts
    // instead, so the stale pre-rewrite values don't linger on screen the whole time.
    dispatch(sandboxChatRewriteStarted())
    const res = await startRewrite(chapter, branchId ?? '', feedback)
    if (!res.ok) {
      dispatch(sandboxChatEventApplied({ type: 'story_sandbox_error', error: res.error ?? '重写失败' }))
    }
  }

  const handleRetryDerive = async () => {
    if (busy || isSyncing) return
    const res = await retryDerive(chapter, branchId ?? '')
    if (!res.ok) {
      dispatch(sandboxChatEventApplied({ type: 'story_sandbox_error', error: res.error ?? '重试失败' }))
    }
  }

  const handleRewriteProfileMutation = (feedback: string): void => {
    if (busy || isSyncing) return
    dispatch(sandboxChatProfileMutationRewriteStarted())
    void rewriteProfileMutation(chapter, branchId ?? '', feedback).then((res) => {
      if (!res.ok) {
        dispatch(sandboxChatEventApplied({
          type: 'story_sandbox_profile_mutation_rewrite_error', error: res.error ?? '重写失败',
        }))
        toastError(res.error ?? '重写失败')
      }
    })
  }

  // Fires the actual request -- called either immediately (nothing else busy) or later, once a
  // queued request's wait is over (see the effect below). Not memoized: this file's other
  // handlers are plain per-render closures too (see handleRewrite/handleDeleteBranch above).
  const fireRewriteSelection = async (
    roundId: string, originalText: string, anchorOffset: number, feedback: string,
  ) => {
    dispatch(sandboxChatSelectionRewriteFired({
      roundId, originalText, anchorOffset,
    }))
    const res = await rewriteSelection(chapter, branchId ?? '', originalText, anchorOffset, feedback, roundId)
    if (!res.ok) {
      dispatch(sandboxChatEventApplied({
        type: 'story_sandbox_selection_rewrite_error', error: res.error ?? '重写失败', round_id: roundId,
      }))
      toastError(res.error ?? '重写失败')
    }
  }

  // The context-menu rewrite is meant to work on any already-completed round at any time --
  // including while a new turn is streaming/deriving or another story_sandbox_* task is running
  // -- rather than being disabled until everything settles. When something else is busy, this
  // just holds the request (replacing any previously-queued one) instead of blocking or erroring;
  // the effect below fires it the moment busy clears.
  const handleRewriteSelection = (
    roundId: string | undefined, originalText: string, anchorOffset: number, feedback: string,
  ) => {
    if (!roundId) {
      toastError('本轮尚未就绪，暂时无法重写选中片段')
      return
    }
    if (busy || isSyncing) {
      dispatch(sandboxChatSelectionRewriteQueued({ roundId, originalText, anchorOffset, feedback }))
      return
    }
    void fireRewriteSelection(roundId, originalText, anchorOffset, feedback)
  }

  useEffect(() => {
    if (busy || isSyncing) return
    const pending = state.pendingSelectionRewrite
    if (!pending) return
    void fireRewriteSelection(pending.roundId, pending.originalText, pending.anchorOffset, pending.feedback)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, isSyncing, state.pendingSelectionRewrite])

  const toggleCat = (cat: TurnFilterCat) => {
    setHiddenCats((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  const activeBranchName = (branchList ?? []).find((b) => b.id === branchId)?.name

  const handleBranchModalSubmit = ({ name, copyFromCurrent }: { name: string; copyFromCurrent: boolean }) => {
    const submittingMode = branchModalMode
    setBranchModalMode(null)
    if (submittingMode === 'create') {
      void createBranch.mutateAsync({
        name: name || undefined, sourceBranchId: copyFromCurrent ? (branchId ?? undefined) : undefined,
      }).then((b) => onBranchChange(b.id)).catch(() => {
        toastError('新建故事线失败，请重试')
      })
    } else if (submittingMode === 'rename' && branchId && name) {
      void renameBranch.mutateAsync({ branchId, name }).catch(() => {
        toastError('重命名失败，请重试')
      })
    }
  }

  const selectedDirectionsSet = new Set(selectedDirections)
  const previewText = buildSubmissionText(input, selectedDirections)
  const recognizedNames = detectRecognizedNames(previewText, characterNames)
  const recognizedSettings = detectRecognizedNames(previewText, settingNames)
  const mentionCandidates = useMemo<MentionCandidate[]>(() => [
    ...characterNames.map((name) => ({ name, type: 'character' as const })),
    ...settingNames.map((name) => ({ name, type: 'setting' as const })),
  ], [characterNames, settingNames])

  return (
    <div className="relative flex flex-col flex-1 min-h-0 min-w-0 border border-slate-200 rounded-lg bg-white overflow-hidden">
      {isSyncing && <ChatHistorySyncOverlay />}
      <div className="shrink-0 px-4 pt-2 pb-2 flex gap-2">
        {TURN_FILTER_CATS.map(({ cat, label }) => (
          <button
            key={cat}
            type="button"
            aria-pressed={!hiddenCats.has(cat)}
            onClick={() => toggleCat(cat)}
            className={`text-xs px-2 py-0.5 rounded-full border ${
              hiddenCats.has(cat)
                ? 'bg-white text-slate-400 border-slate-200'
                : 'bg-slate-100 text-slate-700 border-slate-300'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="relative flex flex-1 min-h-0 flex-col">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3"
        >
        {state.rounds.map((r, i) => (
          <Fragment key={stableRoundKey(r)}>
            {(r.initialStates || r.initialSceneState) && (
              <InitialContextCard
                states={r.initialStates} scene={r.initialSceneState}
                hiddenCats={hiddenCats} forceOpen={expandAll}
                stateDeriveFields={stateDeriveFields}
              />
            )}
            <TurnSegments
              round={r.id ? { ...r, sceneImageUrl: sceneImages[r.id] } : r} hiddenCats={hiddenCats}
              sceneImageChapter={chapter}
              sceneImageBranchId={branchId ?? undefined}
              onGenerateSceneImage={handleGenerateSceneImage}
              selectedDirections={selectedDirectionsSet} onToggleDirection={toggleDirection}
              isLatest={i === state.rounds.length - 1 && !state.liveRound}
              onRegenerate={handleRegenerate}
              onRewrite={(feedback) => void handleRewrite(feedback)}
              rewriting={state.rewritingProse !== null}
              rewritingProse={state.rewritingProse ?? undefined}
              onRewriteSelection={(originalText, anchorOffset, feedback) => (
                handleRewriteSelection(r.id, originalText, anchorOffset, feedback)
              )}
              selectionRewriting={r.id != null && r.id === state.selectionRewritingRoundId}
              selectionRewriteAnchor={
                r.id != null && r.id === state.selectionRewritingRoundId
                  ? state.selectionRewritingAnchor ?? undefined
                  : undefined
              }
              selectionRewriteQueued={r.id != null && r.id === state.pendingSelectionRewrite?.roundId}
              styleGuardRewriting={
                state.rewritingProse !== null && i === state.rounds.length - 1
                  ? state.styleRewriting
                  : undefined
              }
              pendingFields={
                i === state.rounds.length - 1 && !state.liveRound
                  ? state.pendingFields
                  : undefined
              }
              forceOpen={expandAll}
              characterNames={characterNames} settingNames={settingNames}
              onRewriteProfileMutation={handleRewriteProfileMutation}
              profileMutationRewriting={state.profileMutationRewriting}
              stateDeriveFields={stateDeriveFields}
            />
            {i === state.rounds.length - 1 && !state.liveRound && r.errorCode && (
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="accent"
                  disabled={busy || isSyncing || state.rewritingProse !== null}
                  onClick={() => void handleRetryDerive()}
                  className="text-xs hover:bg-[var(--c-accent)] hover:text-[var(--c-accent-text)]"
                >
                  重试
                </Button>
              </div>
            )}
          </Fragment>
        ))}
        {state.liveRound && (
          <>
            {state.rounds.length === 0 && (
              state.pendingFields.initialStates || state.liveRound.initialStates
              || state.pendingFields.initialSceneState || state.liveRound.initialSceneState
            ) && (
              <InitialContextCard
                states={state.liveRound.initialStates}
                pending={!!state.pendingFields.initialStates}
                scene={state.liveRound.initialSceneState}
                scenePending={!!state.pendingFields.initialSceneState}
                hiddenCats={hiddenCats} forceOpen={expandAll}
                stateDeriveFields={stateDeriveFields}
              />
            )}
            {!state.pendingFields.initialStates && (
              <TurnSegments
                round={state.liveRound} hiddenCats={hiddenCats}
                selectedDirections={selectedDirectionsSet} onToggleDirection={toggleDirection}
                isLatest={false}
                styleGuardRewriting={state.styleRewriting}
                pendingFields={state.pendingFields}
                forceOpen={expandAll}
                loadingStatus={state.status || undefined}
                onRewriteProfileMutation={handleRewriteProfileMutation}
                profileMutationRewriting={state.profileMutationRewriting}
                stateDeriveFields={stateDeriveFields}
              />
            )}
          </>
        )}
        </div>
        <ChatScrollToTopButton visible={showScrollToTop} onClick={scrollToTop} />
        <ChatScrollToBottomButton
          visible={showScrollToBottom} hasNewContent={hasNewContentBelow} onClick={scrollToBottom}
        />
      </div>
      <div className="relative z-20 shrink-0 min-w-0 border-t border-slate-200 bg-slate-50 p-3">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <Button
            type="button"
            variant="accent"
            size="xs"
            onClick={() => handleModeChange(mode === 'free' ? 'chapter' : 'free')}
            aria-label="切换自由/章节模式"
            title="点击切换到另一种模式"
          >
            {mode === 'free' ? '自由' : '章节'}
          </Button>
          {mode === 'chapter' && (
            <Select
              value={String(selectedChapter)}
              onValueChange={(v) => onSelectChapter(Number(v))}
              disabled={chapters.length === 0}
            >
              <SelectTrigger size="xs">
                <SelectValue placeholder="章节" />
              </SelectTrigger>
              <SelectContent size="xs">
                {chapters.map((ch) => <SelectItem key={ch} value={String(ch)}>第{ch}章</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          <Select
            value={branchId ?? ''}
            onValueChange={(v) => { if (v) onBranchChange(v) }}
            disabled={!branchList || branchList.length === 0}
          >
            <SelectTrigger size="xs" className="min-w-20">
              <SelectValue placeholder="故事线" />
            </SelectTrigger>
            <SelectContent size="xs">
              {(branchList ?? []).map((b) => (
                <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <StorySandboxBranchMenu
            branchId={branchId}
            busy={busy}
            isSyncing={isSyncing}
            onCreate={() => setBranchModalMode('create')}
            onRename={() => setBranchModalMode('rename')}
            onReset={handleResetBranch}
            onDelete={handleDeleteBranch}
          />
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => setExpandAll((v) => (v === true ? false : true))}
            title={expandAll === true ? '折叠对话中所有状态/走向卡片' : '展开对话中所有状态/走向卡片'}
          >
            {expandAll === true ? '折叠全部' : '展开全部'}
          </Button>
        </div>
        <div
          className={`flex flex-col gap-2 p-2 rounded-md border border-slate-300 shadow-sm ${
            inputDisabled ? 'bg-slate-100' : 'bg-white'
          }`}
        >
          <SelectedDirectionsCard
            directions={selectedDirections}
            onRemove={toggleDirection}
          />
          <SelectedMemoriesCard
            memories={selectedMemories}
            onRemove={onRemoveMemory}
          />
          <ChatComposerBar
            ref={composerRef}
            bare
            value={input}
            disabled={inputDisabled}
            busy={busy}
            cancelling={cancelling}
            onChange={setInput}
            onSubmit={() => void submit()}
            onCancel={() => void cancelTurn()}
            onKeyDown={(e) => composerHistory.handleKey(e, input, setInput)}
            placeholder={
              isSyncing ? CHAT_HISTORY_SYNC_LABEL : '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…'
            }
            mentionCandidates={mentionCandidates}
          />
          {recognizedNames.length > 0 && (
            <p className="text-[11px] text-slate-400">识别到角色：{recognizedNames.join('、')}</p>
          )}
          {recognizedSettings.length > 0 && (
            <p className="text-[11px] text-slate-400">识别到设定：{recognizedSettings.join('、')}</p>
          )}
        </div>
      </div>
      {branchModalMode && (
        <StorySandboxBranchModal
          mode={branchModalMode}
          currentBranchName={activeBranchName}
          defaultName={branchModalMode === 'rename' ? activeBranchName ?? '' : ''}
          onSubmit={handleBranchModalSubmit}
          onClose={() => setBranchModalMode(null)}
        />
      )}
    </div>
  )
}
