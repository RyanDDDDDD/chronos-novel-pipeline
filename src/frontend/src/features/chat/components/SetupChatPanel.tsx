import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, FileText, Loader2, Paperclip, X } from 'lucide-react'
import SetupChatQueueBar from '@/features/chat/components/SetupChatQueueBar'
import ChatComposerBar from '@/shared/components/ChatComposerBar'
import { useComposerHistory } from '@/shared/hooks/useComposerHistory'
import ChatHistorySyncOverlay, { CHAT_HISTORY_SYNC_LABEL } from '@/shared/components/ChatHistorySyncOverlay'
import ChatMarkdown from '@/shared/components/ChatMarkdown'
import CopyButton from '@/shared/components/CopyButton'
import RegenerateButton from '@/shared/components/RegenerateButton'
import { FilterMenu } from '@/shared/components/mention/FilterMenu'
import { useSetupSkills } from '@/shared/queries/setup'
import { novelsKey } from '@/shared/queries/keys'
import {
  deleteSetupChatAttachment,
  fetchSetupChatAttachmentStatus,
  fetchSetupChatStatus,
  filterSlashMenu,
  isImageAttachmentFilename,
  stripMemoryForDisplay,
  uploadSetupChatAttachment,
  type SetupChatAttachment,
  type ChatEvent,
} from '@/shared/utils/setup'
import { sortFilesByNaturalFilename } from '@/shared/utils/filenameSort'
import { useWsClient } from '@/shared/hooks/useWsClient'
import { selectConnected } from '@/shared/store/connectionSlice'
import { selectNovelImportProgress } from '@/features/chat/store/novelImportSlice'
import ProgressBar from '@/shared/components/ProgressBar'
import { Button } from '@/shared/components/ui/button'
import { Bubble } from '@/shared/components/ui/bubble'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import {
  MessageScrollerProvider,
  MessageScroller,
  MessageScrollerViewport,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerButton,
} from '@/shared/components/ui/message-scroller'
import { Checkbox } from '@/shared/components/ui/checkbox'
import { Input } from '@/shared/components/ui/input'
import {
  Attachment,
  AttachmentAction,
  AttachmentActions,
  AttachmentContent,
  AttachmentGroup,
  AttachmentMedia,
  AttachmentTitle,
} from '@/shared/components/ui/attachment'
import { useToast } from '@/shared/hooks/useToast'
import {
  selectSetupChatBusy, selectSetupChatMessageQueue, selectSetupChatPendingChoice, selectSetupChatAutoMode,
  clearSetupChatPendingChoice as clearSetupChatPendingChoiceAction,
  sendSetupChatMessage as sendSetupChatMessageThunk,
  regenerateSetupChatTurn as regenerateSetupChatTurnThunk,
  resetSetupChatConversation as resetSetupChatConversationThunk,
  setSetupChatAutoMode as setSetupChatAutoModeThunk,
  stopSetupChatTurn as stopSetupChatTurnThunk,
  hydrateSetupChat, selectSetupChatState, selectSetupChatHydrating, selectSetupChatHydrateEpoch,
  setupChatMessageSubmitted, setupChatMessageQueued, setupChatMessageQueueRemoved,
  setupChatEventApplied, setupChatCleared, setupChatRegenerateStarted,
} from '@/features/chat/store/setupChatSlice'
import type { AppDispatch } from '@/shared/store/store'
import { formatChoiceSubmission, allChoiceIndices } from '@/features/chat/utils/setupChatState'

export type { ChatMsg, ChatState } from '@/features/chat/utils/setupChatState'
export { formatChoiceMessage, formatChoiceSubmission, allChoiceIndices, reduceChatEvent } from '@/features/chat/utils/setupChatState'

//Only the input draft is cached for page switching/refresh recovery now -- conversation content
//(messages/live/status) lives in Redux (setupChatSlice.chat), which survives a remount on its
//own (see hydrateSetupChat), so it no longer needs a sessionStorage round-trip.
export type UiCache = { draft?: string }

export function loadUiCache(storageKey: string): UiCache {
  try {
    const raw = sessionStorage.getItem(storageKey)
    if (!raw) return {}
    return JSON.parse(raw) as UiCache
  } catch {
    return {}
  }
}

export function saveUiCache(storageKey: string, cache: UiCache): void {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(cache))
  } catch {
    /*sessionStorage full/disabled → ignored, cache is only a cross-page/refresh UX optimization*/
  }
}

export { isNearBottom } from '@/shared/hooks/useChatScrollFollow'
export { resizeTextareaToFit } from '@/shared/components/ChatComposerInput'

export default function SetupChatPanel({
  novelId,
  cacheKey,
}: {
  novelId: string
  cacheKey: string
}) {
  const dispatch = useDispatch<AppDispatch>()
  const ws = useWsClient()
  const connected = useSelector(selectConnected)
  const busy = useSelector(selectSetupChatBusy)
  const messageQueue = useSelector(selectSetupChatMessageQueue)
  // Redux-backed, survives panel unmount; drained by listenerMiddleware (see listeners.ts), not here.
  const pendingChoice = useSelector(selectSetupChatPendingChoice)
  const clearPendingChoice = useCallback(() => dispatch(clearSetupChatPendingChoiceAction()), [dispatch])
  const sendSetupChatMessage = useCallback(
    (text: string, attachmentIds?: string[]) =>
      dispatch(sendSetupChatMessageThunk({ text, attachmentIds })).unwrap(),
    [dispatch],
  )
  const regenerateSetupChatTurn = useCallback(
    (text: string) => dispatch(regenerateSetupChatTurnThunk(text)).unwrap(),
    [dispatch],
  )
  const resetSetupChatConversation = useCallback(
    () => dispatch(resetSetupChatConversationThunk()).unwrap(),
    [dispatch],
  )
  const stopTurn = useCallback(
    () => dispatch(stopSetupChatTurnThunk()).unwrap(),
    [dispatch],
  )
  const autoMode = useSelector(selectSetupChatAutoMode)
  const onToggleAutoMode = useCallback(
    (auto: boolean) => dispatch(setSetupChatAutoModeThunk(auto)).unwrap(),
    [dispatch],
  )
  const queryClient = useQueryClient()
  const state = useSelector(selectSetupChatState)
  const historyEntries = useMemo(
    () => state.messages.filter((m) => m.role === 'user').map((m) => m.content),
    [state.messages],
  )
  const composerHistory = useComposerHistory(historyEntries)
  const isSyncing = useSelector(selectSetupChatHydrating)
  const [input, setInput] = useState<string>(() => loadUiCache(cacheKey).draft ?? '')
  const pendingTextRef = useRef('')
  const [cancelling, setCancelling] = useState(false)
  const { confirm, error: toastError } = useToast()
  const novelImport = useSelector(selectNovelImportProgress(novelId))
  const [attachments, setAttachments] = useState<SetupChatAttachment[]>([])
  const [imageRecognitionConfigured, setImageRecognitionConfigured] = useState(true)
  const [dragDepth, setDragDepth] = useState(0)
  const isDraggingFile = dragDepth > 0
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [choiceCustomText, setChoiceCustomText] = useState('')
  const [menuIdx, setMenuIdx] = useState(0)
  const [menuDismissed, setMenuDismissed] = useState(false)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const novelIdRef = useRef(novelId)
  //Latest clearPendingChoice without putting it in effect deps: the default value (and any
  //inline callback a caller passes) is a fresh function identity every render, which would
  //otherwise re-fire the novel-switch effect below on every render (setState → re-render → new
  //identity → effect fires → setState → ... infinite loop).
  const clearPendingChoiceRef = useRef(clearPendingChoice)
  clearPendingChoiceRef.current = clearPendingChoice

  const { data: setupSkills } = useSetupSkills()
  const slashMenu = menuDismissed || busy ? null : filterSlashMenu(input, setupSkills ?? [])

  //输入变化时重置菜单游标；离开斜杠态解除 Esc 的关闭记忆
  useEffect(() => {
    setMenuIdx(0)
    if (!input.startsWith('/')) setMenuDismissed(false)
  }, [input])

  const pickSlash = (name: string) => {
    setInput(`/${name} `)
  }

  // Redux (setupChatSlice.chat) is never destroyed on unmount -- a setup_chat_* WS event keeps
  // being folded into it via wsMiddleware/wsEventReceived regardless of what's mounted. This
  // hydrate call is a no-op (see hydrateSetupChat's historyLoadedNovel guard) once this novel has
  // already been fetched once, so a remount never loses an in-flight turn's content to a stale
  // sessionStorage/react-query snapshot the way the old design could. hydrateEpoch is included so
  // resetForNovelSwitch() re-triggers hydration after a stale in-flight fetch is discarded.
  const hydrateEpoch = useSelector(selectSetupChatHydrateEpoch)
  useEffect(() => {
    void dispatch(hydrateSetupChat(novelId))
  }, [dispatch, novelId, hydrateEpoch])

  useEffect(() => {
    let cancelled = false
    void fetchSetupChatStatus(novelId).then((status) => {
      if (!cancelled) setImageRecognitionConfigured(status.imageRecognitionConfigured)
    })
    return () => {
      cancelled = true
    }
  }, [novelId])

  const processingAttachmentIds = useMemo(
    () => attachments.filter((a) => a.status === 'processing').map((a) => a.attachment_id),
    [attachments],
  )

  useEffect(() => {
    if (processingAttachmentIds.length === 0) return
    let cancelled = false
    const poll = async () => {
      for (const attachmentId of processingAttachmentIds) {
        const status = await fetchSetupChatAttachmentStatus(attachmentId)
        if (cancelled || !status) continue
        setAttachments((prev) =>
          prev.map((a) =>
            a.attachment_id === attachmentId
              ? { ...a, status: status.status, error: status.error }
              : a,
          ),
        )
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 800)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [processingAttachmentIds])

  const hasImageAttachments = attachments.some((a) => isImageAttachmentFilename(a.filename))
  const hasProcessingAttachments = processingAttachmentIds.length > 0
  const visionBlocked = hasImageAttachments && !imageRecognitionConfigured

  // Set whenever the novel-switch effect below calls setInput(), so the persist effect's very
  // next run -- which fires in the SAME commit since it also depends on cacheKey -- skips
  // writing the stale (pre-restore) `input` closure value back over what was just restored.
  // Mirrors the identical fix in StorySandboxPanel.tsx, where this race is easier to trigger
  // (branchId there settles across two renders instead of one) but the underlying hazard --
  // two sibling effects both reacting to a scope-identity change, one restoring `input` and the
  // other persisting it -- is the same here.
  const restoringRef = useRef(false)

  useEffect(() => {
    const novelSwitched = novelIdRef.current !== novelId
    novelIdRef.current = novelId
    //A pending choice belongs to the novel it was asked in; don't carry it across a switch.
    if (novelSwitched) {
      restoringRef.current = true
      clearPendingChoiceRef.current()
      setInput(loadUiCache(cacheKey).draft ?? '')
      setAttachments((prev) => {
        for (const a of prev) {
          void deleteSetupChatAttachment(a.attachment_id)
        }
        return []
      })
      setDragDepth(0)
    }
  }, [novelId, cacheKey])

  //Persist only the input draft to sessionStorage (cacheKey isolated by novel) for recovery
  //after page cutting/refreshing -- conversation content lives in Redux now.
  useEffect(() => {
    if (restoringRef.current) {
      restoringRef.current = false
      return
    }
    saveUiCache(cacheKey, { draft: input })
  }, [cacheKey, input])

  useEffect(() => {
    setChecked(new Set())
    setChoiceCustomText('')
  }, [pendingChoice])

  // Redux's wsEventReceived case already folds every setup_chat_* event into chat/busy/
  // pendingChoice regardless of mount state -- this listener only handles side effects that
  // aren't pure state folding (react-query cache invalidation, toasts, composer-text restore on
  // cancel).
  useEffect(() => {
    if (!ws || !connected) return
    const onMsg = (e: MessageEvent) => {
      try {
        const ev = JSON.parse(e.data as string) as ChatEvent
        if (ev.type?.startsWith('setup_chat_')) {
          if (ev.type === 'setup_chat_done') {
            // A turn may have called agent tools that mutate novel-level metadata (e.g.
            // rename_novel_title) which the sidebar's novel list otherwise has no way to learn
            // about -- unlike the manual rename flow (useNovelActions), which invalidates this
            // key itself right after its REST call.
            void queryClient.invalidateQueries({ queryKey: novelsKey })
          }
          if (ev.type === 'setup_chat_turn_cancelled') {
            setInput(pendingTextRef.current)
            if (ev.rollback_failed) toastError('状态可能未完全回滚，建议刷新核实')
          }
        }
      } catch {
        /*Non setup_chat events ignored*/
      }
    }
    ws.addEventListener('message', onMsg)
    return () => ws.removeEventListener('message', onMsg)
  }, [ws, connected, queryClient, toastError])

  const submitText = async (text: string) => {
    const t = text.trim()
    if (!t && attachments.length === 0) return
    if (hasProcessingAttachments) {
      toastError('图片仍在处理中，请稍候再发送')
      return
    }
    if (visionBlocked) {
      toastError('未绑定视觉模型，无法识别图片。请前往流水线 → 对话 → 图片识别 绑定模型。')
      return
    }
    // No typed text but attachments are present -- send a placeholder so the chat-history
    // bubble (and the same string doubling as the agent-visible message, see
    // start_setup_chat_turn's agent_text composition) isn't blank; the attachment manifest
    // already tells the agent what to do with it.
    const effectiveText = t || `[已上传 ${attachments.length} 个附件]`
    clearPendingChoice()
    const attachmentIds = attachments.map((a) => a.attachment_id)
    setAttachments([])
    if (busy) {
      dispatch(setupChatMessageQueued({ text: effectiveText, attachmentIds }))
      return
    }
    dispatch(setupChatMessageSubmitted({ text: effectiveText }))
    const res = await sendSetupChatMessage(effectiveText, attachmentIds)
    if (!res.ok) {
      dispatch(setupChatEventApplied({ type: 'setup_chat_error', error: res.error ?? '发送失败' }))
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text && attachments.length === 0) return
    pendingTextRef.current = text
    setInput('')
    await submitText(text)
  }

  const cancelTurn = async () => {
    setCancelling(true)
    const res = await stopTurn()
    setCancelling(false)
    if (!res.ok) {
      toastError(res.error ?? '中断失败，请重试')
    }
  }

  const focusComposer = () => {
    const el = composerRef.current
    if (!el) return
    el.focus()
    const end = el.value.length
    el.setSelectionRange(end, end)
  }

  const uploadFiles = async (files: File[]) => {
    let uploadedAny = false
    for (const file of sortFilesByNaturalFilename(files)) {
      const res = await uploadSetupChatAttachment(file)
      if (res.ok) {
        uploadedAny = true
        setAttachments((prev) => [
          ...prev.filter((a) => a.filename !== res.attachment.filename),
          res.attachment,
        ])
        if (res.warning) {
          toastError(res.warning)
        }
        if (isImageAttachmentFilename(res.attachment.filename)) {
          const status = await fetchSetupChatStatus(novelId)
          setImageRecognitionConfigured(status.imageRecognitionConfigured)
          if (!status.imageRecognitionConfigured) {
            toastError('未绑定视觉模型：上传后无法识别图片。请前往流水线 → 对话 → 图片识别 绑定模型。')
          }
        }
      } else {
        toastError(res.error)
      }
    }
    if (uploadedAny) {
      // Defer until attachment chips render; file picker often leaves focus on the upload control.
      window.setTimeout(() => focusComposer(), 0)
    }
  }

  const handleAttachmentPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    await uploadFiles(files)
  }

  const hasFilesInDrag = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes('Files')

  const handleDragEnter = (e: React.DragEvent) => {
    if (isSyncing || !hasFilesInDrag(e)) return
    e.preventDefault()
    setDragDepth((d) => d + 1)
  }

  const handleDragOver = (e: React.DragEvent) => {
    if (isSyncing || !hasFilesInDrag(e)) return
    e.preventDefault() // without this the browser's default action (open the file) fires instead of drop
  }

  const handleDragLeave = (e: React.DragEvent) => {
    if (!hasFilesInDrag(e)) return
    setDragDepth((d) => Math.max(0, d - 1))
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setDragDepth(0)
    if (isSyncing) return
    const files = Array.from(e.dataTransfer.files)
    if (files.length === 0) return
    await uploadFiles(files)
  }

  const removeAttachment = async (attachmentId: string) => {
    setAttachments((prev) => prev.filter((a) => a.attachment_id !== attachmentId))
    await deleteSetupChatAttachment(attachmentId)
  }

  const clearAllAttachments = async () => {
    const ids = attachments.map((a) => a.attachment_id)
    if (ids.length === 0) return
    setAttachments([])
    await Promise.all(ids.map((id) => deleteSetupChatAttachment(id)))
  }

  const handleClearConversation = async () => {
    if (busy) return
    if (!(await confirm('清空后无法恢复，确定要清空对话重新开始吗？'))) return
    const res = await resetSetupChatConversation()
    if (!res.ok) {
      dispatch(setupChatEventApplied({ type: 'setup_chat_error', error: res.error ?? '清空失败' }))
      return
    }
    dispatch(setupChatCleared())
    clearPendingChoice()
  }

  const regenerateReply = async (assistantMsgId: string) => {
    if (busy || isSyncing) return
    const idx = state.messages.findIndex((m) => m.id === assistantMsgId)
    if (idx <= 0) return
    const userMsg = state.messages[idx - 1]
    if (userMsg.role !== 'user') return
    dispatch(setupChatRegenerateStarted({ assistantMsgId }))
    const res = await regenerateSetupChatTurn(userMsg.content)
    if (!res.ok) {
      dispatch(setupChatEventApplied({ type: 'setup_chat_error', error: res.error ?? '重新生成失败' }))
    }
  }

  return (
    <div
      data-testid="setup-chat-panel"
      className="relative flex flex-col flex-1 min-h-0 min-w-0 border border-slate-200 rounded-lg bg-white overflow-hidden"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(e) => void handleDrop(e)}
    >
      {isSyncing && <ChatHistorySyncOverlay />}
      {isDraggingFile && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-white/70 backdrop-blur-sm pointer-events-none">
          <div className="flex flex-col items-center gap-2 rounded-lg border-2 border-dashed border-[var(--c-accent)] bg-white px-8 py-6 text-[var(--c-accent)] shadow-float">
            <Paperclip size={28} />
            <span className="text-sm font-medium">松开鼠标上传文件到对话</span>
          </div>
        </div>
      )}
      <div className="relative flex flex-1 min-h-0 flex-col">
        <MessageScrollerProvider autoScroll defaultScrollPosition="end">
          <MessageScroller className="flex-1 min-h-0">
            <MessageScrollerViewport className="overflow-x-hidden px-4 py-4 sm:px-6">
              <MessageScrollerContent className="gap-3">
        {state.messages.map((m, i) =>
          m.role === 'system' ? (
            <MessageScrollerItem key={m.id} messageId={m.id}>
            <div className="flex justify-center">
              <p className="max-w-[90%] px-2 text-center text-xs text-slate-500">{m.content}</p>
            </div>
            </MessageScrollerItem>
          ) : (
            <MessageScrollerItem key={m.id} messageId={m.id}>
            <div className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`flex flex-col max-w-[85%] min-w-0 ${
                  m.role === 'user' ? 'items-end' : 'items-start'
                }`}
              >
                <div
                  className={`min-w-0 rounded-lg px-4 py-2.5 text-[length:var(--reading-font-size)] leading-relaxed ${
                    m.role === 'user'
                      ? 'rounded-tr-sm bg-[var(--c-accent)] text-[var(--c-accent-text)] whitespace-pre-wrap'
                      : 'rounded-tl-sm bg-white border border-slate-200 shadow-sm text-slate-700'
                  }`}
                >
                  {m.role === 'assistant' ? (
                    <>
                      {m.thinking && (
                        <Collapsible defaultOpen={false} className="mb-2 text-xs">
                          <Bubble variant="ghost" className="text-[color:var(--c-text-muted)]">
                            <CollapsibleTrigger className="cursor-pointer select-none hover:text-[color:var(--c-text-secondary)]">
                              💭 思考过程
                            </CollapsibleTrigger>
                            <CollapsibleContent className="mt-1 border-l-2 border-[var(--c-border)] pl-2">
                              <ChatMarkdown content={m.thinking} />
                            </CollapsibleContent>
                          </Bubble>
                        </Collapsible>
                      )}
                      <ChatMarkdown content={m.content} />
                    </>
                  ) : (
                    m.content
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-0.5">
                  <CopyButton
                    text={m.content}
                    className="text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                  />
                  {m.role === 'assistant' && i === state.messages.length - 1 && (
                    <RegenerateButton
                      disabled={busy || isSyncing}
                      onClick={() => void regenerateReply(m.id)}
                      className="text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                    />
                  )}
                </div>
              </div>
            </div>
            </MessageScrollerItem>
          ),
        )}
        {pendingChoice && (
          <MessageScrollerItem messageId="pending-choice">
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-lg rounded-tl-sm border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm">
              <div className="font-medium text-slate-700 mb-2">{pendingChoice.question}</div>
              <div className="space-y-1.5">
                {pendingChoice.options.map((opt, i) => (
                  <label key={i} className="flex items-center gap-2 text-slate-600">
                    <Checkbox
                      checked={checked.has(i)}
                      onCheckedChange={() => {
                        setChecked((prev) => {
                          const next = new Set(prev)
                          if (next.has(i)) next.delete(i)
                          else next.add(i)
                          return next
                        })
                      }}
                    />
                    {opt}
                  </label>
                ))}
              </div>
              <Input
                type="text"
                value={choiceCustomText}
                onChange={(e) => setChoiceCustomText(e.target.value)}
                disabled={isSyncing}
                placeholder="或输入自己的意见…"
                aria-label="补充意见"
                className="mt-3"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    const labels = [...checked].sort((a, b) => a - b).map((i) => pendingChoice.options[i])
                    const message = formatChoiceSubmission(labels, choiceCustomText)
                    if (!message) return
                    setChecked(new Set())
                    setChoiceCustomText('')
                    void submitText(message)
                  }
                }}
              />
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {pendingChoice.options.length > 1 && (
                  <Button
                    type="button"
                    variant="accent"
                    disabled={checked.size === pendingChoice.options.length}
                    onClick={() => setChecked(allChoiceIndices(pendingChoice.options.length))}
                  >
                    全选
                  </Button>
                )}
                <Button
                  type="button"
                  variant="default"
                  disabled={checked.size === 0 && !choiceCustomText.trim()}
                  onClick={() => {
                    const labels = [...checked].sort((a, b) => a - b).map((i) => pendingChoice.options[i])
                    setChecked(new Set())
                    setChoiceCustomText('')
                    void submitText(formatChoiceSubmission(labels, choiceCustomText))
                  }}
                >
                  {checked.size > 0 ? `确认（${checked.size}）` : '确认'}
                </Button>
              </div>
            </div>
          </div>
          </MessageScrollerItem>
        )}
        {state.status && (
          <MessageScrollerItem messageId="status-indicator">
          <div className="flex justify-start">
            <div className="flex items-center gap-1.5 max-w-[85%] min-w-0 rounded-lg rounded-tl-sm border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-500 shadow-sm italic">
              <Loader2 size={14} className="animate-spin shrink-0" aria-hidden />
              {state.status}
            </div>
          </div>
          </MessageScrollerItem>
        )}
        {state.live && (
          <MessageScrollerItem messageId="live-stream">
          <div className="flex justify-start">
            <div className="max-w-[85%] min-w-0 rounded-lg rounded-tl-sm border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-500 shadow-sm">
              <ChatMarkdown content={stripMemoryForDisplay(state.live)} />
            </div>
          </div>
          </MessageScrollerItem>
        )}
              </MessageScrollerContent>
            </MessageScrollerViewport>
            <MessageScrollerButton
              direction="start"
              render={<button type="button" />}
              className="chat-scroll-jump-btn inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-sm font-medium"
            >
              <ChevronUp size={16} aria-hidden />
              跳转至顶部
            </MessageScrollerButton>
            <MessageScrollerButton
              direction="end"
              render={<button type="button" />}
              className="chat-scroll-jump-btn inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-sm font-medium"
            >
              <ChevronDown size={16} aria-hidden />
              跳转至底部
            </MessageScrollerButton>
          </MessageScroller>
        </MessageScrollerProvider>
      </div>
      <div className="relative shrink-0 min-w-0">
        <SetupChatQueueBar
          items={messageQueue}
          onRemove={(id) => dispatch(setupChatMessageQueueRemoved(id))}
        />
        <div className="min-w-0 overflow-x-hidden border-t border-slate-200 bg-slate-50 px-4 py-3 sm:px-6">
        <div className="relative">
        <FilterMenu
          open={!!slashMenu && slashMenu.length > 0}
          items={slashMenu?.map((s) => ({ id: s.name, label: `/${s.name}`, sublabel: s.description })) ?? []}
          highlightedId={slashMenu?.[menuIdx]?.name}
          onSelect={pickSlash}
          onOpenChange={(next) => { if (!next) setMenuDismissed(true) }}
          anchor={<div className="pointer-events-none absolute inset-x-0 bottom-0" aria-hidden />}
        />
        {novelImport.status === 'running' && (
          <div className="mb-2 space-y-1">
            <span className="text-[11px] text-slate-500">
              {novelImport.kind === 'image' ? '识别图片中' : '提炼设定中'}
            </span>
            <ProgressBar index={novelImport.index} total={novelImport.total} />
          </div>
        )}
        {visionBlocked && (
          <div className="mb-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            未绑定视觉模型，发送后无法识别图片。请前往流水线 → 对话 → 图片识别 绑定支持图片输入的模型。
          </div>
        )}
        {attachments.length > 0 && (
          <AttachmentGroup className="mb-2 max-h-24 items-center gap-1.5">
            {attachments.map((a) => (
              <Attachment
                key={a.attachment_id}
                size="xs"
                state={a.status === 'processing' ? 'processing' : a.status === 'error' ? 'error' : 'done'}
                className="min-w-0 gap-1 px-1.5 py-0.5"
              >
                <AttachmentMedia className="w-5 rounded-md p-0.5 [&_svg:not([class*='size-'])]:size-3">
                  {a.status === 'processing' ? <Loader2 size={10} className="animate-spin" /> : <FileText size={10} />}
                </AttachmentMedia>
                <AttachmentContent>
                  <AttachmentTitle className="text-[11px]">{a.filename}</AttachmentTitle>
                </AttachmentContent>
                <AttachmentActions>
                  <AttachmentAction
                    title="移除附件"
                    aria-label={`移除${a.filename}`}
                    className="size-5"
                    onClick={() => void removeAttachment(a.attachment_id)}
                  >
                    <X size={8} />
                  </AttachmentAction>
                </AttachmentActions>
              </Attachment>
            ))}
            <Button
              type="button"
              variant="outline"
              size="xs"
              disabled={isSyncing}
              onClick={() => void clearAllAttachments()}
              className="shrink-0"
            >
              清空
            </Button>
          </AttachmentGroup>
        )}
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <Button variant="outline" size="xs" asChild disabled={isSyncing}>
            <label
              title="上传 .txt / .md / 图片附件"
              className={isSyncing ? 'pointer-events-none' : 'cursor-pointer'}
            >
              <Paperclip size={12} />
              上传附件
              <input
                type="file"
                accept=".txt,.md,.png,.jpg,.jpeg,.webp"
                multiple
                aria-label="上传附件"
                disabled={isSyncing}
                className="hidden"
                onChange={(e) => void handleAttachmentPick(e)}
              />
            </label>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="xs"
            disabled={isSyncing}
            aria-pressed={autoMode}
            onClick={() => void onToggleAutoMode(!autoMode)}
            title={autoMode ? 'AI 自主决策所有细节，结束时汇总，请事后复核' : '开启后 AI 不再逐字段追问，自主完成本次请求'}
          >
            {autoMode ? 'AUTO 已开启' : '切至 AUTO'}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => void handleClearConversation()}
            disabled={busy || isSyncing}
            title="清空全部对话记录，无法恢复"
            className="ml-auto hover:border-red-300 hover:bg-red-50 hover:text-red-600"
          >
            清空对话
          </Button>
        </div>
        <ChatComposerBar
          ref={composerRef}
          value={input}
          disabled={isSyncing}
          busy={busy}
          cancelling={cancelling}
          onChange={setInput}
          onSubmit={() => void send()}
          onCancel={() => void cancelTurn()}
          onKeyDown={(e) => {
            if (slashMenu && slashMenu.length > 0) {
              if (e.key === 'ArrowDown') { e.preventDefault(); setMenuIdx((i) => (i + 1) % slashMenu.length); return }
              if (e.key === 'ArrowUp') { e.preventDefault(); setMenuIdx((i) => (i - 1 + slashMenu.length) % slashMenu.length); return }
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); pickSlash(slashMenu[Math.min(menuIdx, slashMenu.length - 1)].name); return }
              if (e.key === 'Escape') { e.preventDefault(); setMenuDismissed(true); return }
            }
            composerHistory.handleKey(e, input, setInput)
          }}
          placeholder={
            isSyncing
              ? CHAT_HISTORY_SYNC_LABEL
              : busy
                ? '处理中…可继续输入，消息将排队发送（Enter 发送）'
                : '和设定共创者对话…（Enter 发送，Shift+Enter 换行）'
          }
        />
        </div>
        </div>
      </div>
    </div>
  )
}
