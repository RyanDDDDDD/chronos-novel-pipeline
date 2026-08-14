import { useEffect, useRef } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import { Routes, Route, Navigate, useNavigate, useLocation, useParams } from 'react-router-dom'
import Header from '@/shared/components/Header'
import NovelRail from '@/shared/components/NovelRail'
import Toaster from '@/shared/components/Toaster'
import { Toaster as Sonner } from '@/shared/components/ui/sonner'
import { TooltipProvider } from '@/shared/components/ui/tooltip'
import BackgroundJobToast from '@/shared/components/BackgroundJobToast'
import SetupPage from '@/features/setup/components/SetupPage'
import SetupChatPage from '@/features/chat/components/SetupChatPage'
import StorySandboxPage from '@/features/sandbox/components/StorySandboxPage'
import ServiceConfigPage from '@/features/services/components/ServiceConfigPage'
import AuthorLoopPage from '@/features/author/components/AuthorLoopPage'
import ChapterManuscriptPage from '@/features/manuscript/components/ChapterManuscriptPage'
import PipelineWorkflowConfigView from '@/features/pipeline/components/PipelineWorkflowConfigView'
import TokenStatsDashboard from '@/features/stats/components/TokenStatsDashboard'
import { useWsClient } from '@/shared/hooks/useWsClient'
import { useToast } from '@/shared/hooks/useToast'
import { persistChapter, readStoredChapter, clearStoredChapter } from '@/shared/utils/chapterStorage'
import { useChapters } from '@/shared/queries/chapters'
import {
  chaptersKey, novelsKey, manuscriptChaptersKey, manuscriptKey, setupKey,
} from '@/shared/queries/keys'
import { switchNovel, type Novel } from '@/shared/utils/novels'
import { viewFromPathname, resolveNovelSwitch, setupTabFromPathname, SETUP_TABS, type SetupTab } from '@/shared/utils/novelRoute'
import { useQueryClient } from '@tanstack/react-query'
import { useNovels, useActiveNovelId } from '@/shared/queries/novels'
import { viewFocusChanged, selectViewUnreadForNovel } from '@/shared/store/viewUnreadSlice'
import type { AppDispatch, RootState } from '@/shared/store/store'
import { selectConnected } from '@/shared/store/connectionSlice'
import { selectAuthorLoopLastAutoSave, authorLoopAutoSaveConsumed } from '@/features/author/store/authorLoopSlice'
import { setChapter as setChapterAction, selectChapter, selectNovelSwitchOverlayVisible, clearNovelSwitchTarget, selectNovelSwitchTarget } from '@/shared/store/uiSlice'
import NovelSwitchOverlay from '@/shared/components/NovelSwitchOverlay'
import { resetForNovelSwitch } from '@/shared/store/resetForNovelSwitch'

function SetupTabRoute() {
  const navigate = useNavigate()
  const novelId = useParams().novelId ?? ''
  const { tab } = useParams<{ tab: string }>()
  const validTab = tab && (SETUP_TABS as string[]).includes(tab) ? (tab as SetupTab) : null
  useEffect(() => {
    if (!validTab) navigate(`/novel/${novelId}/setup/world`, { replace: true })
  }, [validTab, novelId, navigate])
  if (!validTab) return null
  return <SetupPage tab={validTab} />
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const novelId = useParams().novelId ?? ''
  const currentView = viewFromPathname(location.pathname)
  const dispatch = useDispatch<AppDispatch>()

  const connected = useSelector(selectConnected)
  const ws = useWsClient()
  const lastAutoSave = useSelector(selectAuthorLoopLastAutoSave)
  const chapter = useSelector(selectChapter)
  const isViewingArchives = setupTabFromPathname(location.pathname) === 'archives'

  const switchingRef = useRef<string | null>(null)
  const queryClient = useQueryClient()
  const { data: novels = [] } = useNovels()
  const activeNovelId = useActiveNovelId()
  const viewUnread = useSelector(selectViewUnreadForNovel(activeNovelId))
  const showNovelSwitchOverlay = useSelector((s: RootState) =>
    selectNovelSwitchOverlayVisible(s, currentView, activeNovelId),
  )
  const novelSwitchTarget = useSelector(selectNovelSwitchTarget)
  const { toasts, dismiss, success, error: toastError } = useToast()

  // Records what the user is currently looking at (novel + tab) so the badge slice can tell
  // "novel A has an update while I'm on novel B" apart from "I'm already staring at this tab".
  useEffect(() => {
    if (!activeNovelId) return
    dispatch(viewFocusChanged({ novelId: activeNovelId, view: currentView, isArchives: isViewingArchives }))
  }, [activeNovelId, currentView, isViewingArchives, dispatch])

  // Each novel remembers its chapter; restored on load/switch.
  useEffect(() => {
    if (activeNovelId) dispatch(setChapterAction(readStoredChapter(activeNovelId)))
  }, [activeNovelId, dispatch])

  // Persist the current chapter selection for this novel. Also fires once, harmlessly, right
  // after the restore-on-switch effect above writes back the same value it just read.
  useEffect(() => {
    persistChapter(activeNovelId, chapter)
  }, [activeNovelId, chapter])

  const { data: availableChapters = [{ chapter: 1, title: null }], isSuccess: chaptersLoaded } =
    useChapters(activeNovelId)

  //The novelId of the URL is the "intent", and the backend is a single active pointer: if it is inconsistent, it will cut and reset Group C; if it is invalid, it will return to active.
  useEffect(() => {
    const r = resolveNovelSwitch(novelId, novels)
    if (r.action === 'redirect' && r.target) {
      navigate(`/novel/${r.target}/${currentView}`, { replace: true })
    } else if (r.action === 'switch' && r.target) {
      if (switchingRef.current === r.target) return
      const target = r.target
      switchingRef.current = target
      // Optimistically flip the active flag before the POST /api/novels/active round-trip
      // resolves -- useActiveNovelId() (read by every per-novel page) would otherwise keep
      // reporting the OLD novel until that request completes, which under real background
      // concurrency (the backend event loop busy servicing another novel's streaming turn) can
      // take long enough to be visibly perceptible: the sidebar/URL look switched but panels
      // (composer draft, sandbox branch) briefly still show the old novel's content. This never
      // used to be noticeable back when the switch endpoint was near-instant (either idle, or
      // 409-rejected fast) -- see docs/superpowers/specs/2026-08-02-multi-novel-concurrency-
      // design.md's follow-up fix. Reverted (via invalidate) if the request fails below.
      queryClient.setQueryData<Novel[]>(novelsKey, (old) => (
        old?.map((n) => ({ ...n, active: n.id === target })) ?? old
      ))
      // resetForNovelSwitch() must fire in this SAME synchronous batch as the optimistic flip
      // above, not after the REST call succeeds. Once useActiveNovelId() flips instantly, the
      // panels mounted under it (StorySandboxPanel/SetupChatPanel) immediately start hydrating
      // the new novel's conversation history. If the reset were deferred until switchNovel()
      // resolves (as it used to be, when both were driven by the same REST completion), it could
      // land in the middle of that in-flight hydrate: hydrateSandboxChat's own stale-epoch guard
      // correctly discards a result that arrives after a reset -- but nothing re-issues the
      // hydrate afterward, since the panel's effect only re-fires on a scope-identity change,
      // and none happens again once the switch has settled. Net effect: the chat panel stays
      // empty until a full page reload re-mounts everything from scratch. Firing the reset here
      // instead guarantees it always happens BEFORE any hydrate for the new scope can start.
      void dispatch(resetForNovelSwitch(target))
      void (async () => {
        const res = await switchNovel(target)
        if (res.ok) {
          await queryClient.invalidateQueries({ queryKey: novelsKey })
          await queryClient.invalidateQueries({ queryKey: chaptersKey(target) })
          await queryClient.invalidateQueries({ queryKey: manuscriptChaptersKey(target) })
        } else {
          toastError(res.error ?? '切换小说失败')
          // Roll back the optimistic flip -- refetch what the backend actually has active.
          await queryClient.invalidateQueries({ queryKey: novelsKey })
          const fresh = (queryClient.getQueryData(novelsKey) as Novel[] | undefined) ?? novels
          const active = fresh.find(n => n.active)?.id
          if (active) navigate(`/novel/${active}/${currentView}`, { replace: true })
        }
        switchingRef.current = null
      })()
    }
  }, [novelId, novels, currentView, navigate, queryClient, dispatch, toastError])

  // Auto-save orchestration itself lives in the Task 9 listener (store/listeners.ts); this effect
  // only consumes the settled outcome once, to show the toast + invalidate manuscript queries
  // (both are legitimately App-level: Toaster is rendered here, and queryClient isn't
  // Redux-aware).
  useEffect(() => {
    if (!lastAutoSave) return
    if (lastAutoSave.ok) {
      success(`第 ${lastAutoSave.chapter} 章创作完成，成稿已自动保存`)
      void queryClient.invalidateQueries({ queryKey: manuscriptChaptersKey(activeNovelId) })
      void queryClient.invalidateQueries({ queryKey: manuscriptKey(activeNovelId, lastAutoSave.chapter) })
    } else {
      toastError(lastAutoSave.error ?? '成稿自动保存失败')
    }
    dispatch(authorLoopAutoSaveConsumed())
  }, [lastAutoSave, activeNovelId, queryClient, success, toastError, dispatch])

  // setup_chat tools (patch_chapter/generate_one_chapter/edit_character/refine_world) mutate
  // world/cast/plot/skeleton server-side without any per-view invalidation of their own. Without
  // this, e.g. editing a chapter outline via chat leaves the sandbox's cached skeleton stale until
  // its 30s staleTime happens to elapse before the next mount. App is mounted for the whole
  // session, so this catches the mutation regardless of which page is active when it lands.
  useEffect(() => {
    if (!ws || !activeNovelId) return
    const onMsg = (event: MessageEvent) => {
      let data: { type?: string }
      try {
        data = JSON.parse(event.data as string) as { type?: string }
      } catch {
        return
      }
      if (data.type !== 'setup_chat_done') return
      void queryClient.invalidateQueries({ queryKey: setupKey('world', activeNovelId) })
      void queryClient.invalidateQueries({ queryKey: setupKey('cast', activeNovelId) })
      void queryClient.invalidateQueries({ queryKey: setupKey('plot', activeNovelId) })
      void queryClient.invalidateQueries({ queryKey: ['skeleton', activeNovelId] })
      // insert_chapter/delete_chapter shift every later chapter's identity at once -- a
      // targeted per-chapter invalidate can't express "chapter N used to mean something else
      // now", so invalidate every query scoped to this novel that isn't already covered above.
      // This over-invalidates on every setup_chat turn (not just chapter shifts), which is a
      // deliberate, cheap trade: React Query invalidation only marks queries stale for refetch
      // on next access, it doesn't refetch eagerly for unmounted queries.
      void queryClient.invalidateQueries({
        predicate: (query) => query.queryKey.includes(activeNovelId),
      })
      clearStoredChapter(activeNovelId)
    }
    ws.addEventListener('message', onMsg)
    return () => ws.removeEventListener('message', onMsg)
  }, [ws, activeNovelId, queryClient])

  useEffect(() => {
    if (
      chaptersLoaded &&
      availableChapters.length > 0 &&
      !availableChapters.some(c => c.chapter === chapter)
    ) {
      dispatch(setChapterAction(availableChapters[0].chapter))
    }
  }, [chaptersLoaded, availableChapters, chapter, dispatch])

  useEffect(() => {
    if (novelSwitchTarget && !showNovelSwitchOverlay) {
      dispatch(clearNovelSwitchTarget())
    }
  }, [novelSwitchTarget, showNovelSwitchOverlay, dispatch])

  return (
    <TooltipProvider>
    <div className="flex h-screen bg-app overflow-hidden font-sans antialiased">
      <NovelRail />
      <div className="flex flex-col flex-1 min-w-0 min-h-0">
      <Header viewUnread={viewUnread} />

      {!connected && (
        <div className="bg-amber-100 text-amber-800 text-xs px-4 py-2 text-center flex-shrink-0 z-20 shadow-sm border-b border-amber-200">
          ⚠️ 未连接到后端编排器 — 请先运行 <code className="font-mono">uv run python run.py</code>
        </div>
      )}

      <div className="flex flex-1 min-h-0 overflow-hidden">
        <Routes>
          <Route index element={<Navigate to="pipeline" replace />} />
          <Route path="pipeline" element={
            <div className="flex-1 overflow-hidden relative">
              <PipelineWorkflowConfigView novelId={activeNovelId} />
            </div>
          } />
          <Route path="author" element={<AuthorLoopPage />} />
          <Route path="manuscript" element={<ChapterManuscriptPage />} />
          <Route path="setup" element={<Navigate to="world" replace />} />
          <Route path="setup/:tab" element={
            <SetupTabRoute />
          } />
          <Route path="chat" element={<SetupChatPage />} />
          <Route path="sandbox" element={<StorySandboxPage />} />
          <Route path="services" element={<ServiceConfigPage />} />
          <Route path="stats" element={<TokenStatsDashboard />} />
        </Routes>
      </div>
      </div>

      <Toaster toasts={toasts} onDismiss={dismiss} />
      <Sonner />
      <BackgroundJobToast />
      {showNovelSwitchOverlay && <NovelSwitchOverlay />}
    </div>
    </TooltipProvider>
  )
}
