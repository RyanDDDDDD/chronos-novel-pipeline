import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { renderWithProviders, buildTestStore } from '@/test/renderWithClient'
import { Provider } from 'react-redux'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { wsEventReceived } from '@/shared/store/wsActions'
import Toaster from '@/shared/components/Toaster'
import { Toaster as Sonner } from '@/shared/components/ui/sonner'
import { CHAT_HISTORY_SYNC_LABEL } from '@/shared/components/ChatHistorySyncOverlay'
import { useToast } from '@/shared/hooks/useToast'
import type { RootState } from '@/shared/store/store'
import SetupChatPanel, {
  isNearBottom,
  resizeTextareaToFit,
  loadUiCache,
  saveUiCache,
} from './SetupChatPanel'
import {
  allChoiceIndices, formatChoiceMessage, formatChoiceSubmission, reduceChatEvent, EMPTY_CHAT_STATE, type ChatState,
} from '@/features/chat/utils/setupChatState'
import { stripMemoryForDisplay, filterSlashMenu, type SetupSkill } from '@/shared/utils/setup'

// getWsInstance mocked via a vi.hoisted holder (same pattern as StorySandboxPanel.test.tsx) so
// the new interrupt tests can plug in a fake WebSocket-like object; unset (null), this is
// behaviorally identical to the previously-unmocked module (which always resolved to null in
// jsdom), so none of the pre-existing tests below are affected.
const wsHolder = vi.hoisted(() => ({ current: null as WebSocket | null }))
vi.mock('@/shared/store/wsMiddleware', () => ({ getWsInstance: () => wsHolder.current }))

describe('filterSlashMenu', () => {
  const skills: SetupSkill[] = [
    { name: 'foreshadowing', description: '伏笔登记', kind: '', source: 'builtin' },
    { name: 'world-interview', description: '世界观访谈', kind: '', source: 'builtin' },
    { name: 'example-bridges', description: '合成桥段', kind: 'plot-extension', source: 'builtin' },
  ]
  it('输入 / 时列全量（含 plot-extension）', () => {
    expect(filterSlashMenu('/', skills)?.map((s) => s.name)).toEqual(
      ['foreshadowing', 'world-interview', 'example-bridges'])
  })
  it('按前缀过滤且大小写不敏感', () => {
    expect(filterSlashMenu('/WOR', skills)?.map((s) => s.name)).toEqual(['world-interview'])
  })
  it('出现空格（命令已敲完）或非 / 开头时不弹菜单', () => {
    expect(filterSlashMenu('/foreshadowing ', skills)).toBeNull()
    expect(filterSlashMenu('普通消息', skills)).toBeNull()
    expect(filterSlashMenu('', skills)).toBeNull()
  })
})

describe('UiCache round-trip', () => {
  afterEach(() => sessionStorage.clear())

  it('saveUiCache/loadUiCache 只保住输入框草稿（对话内容已迁到 Redux，不再走 sessionStorage）', () => {
    const cache = { draft: '写到一半的话' }
    saveUiCache('setup-chat:default', cache)
    expect(loadUiCache('setup-chat:default')).toEqual(cache)
  })

  it('loadUiCache 缺失键返回空对象', () => {
    expect(loadUiCache('nope')).toEqual({})
  })
})

describe('isNearBottom', () => {
  it('returns true when scrolled to the bottom', () => {
    const el = {
      scrollHeight: 1000,
      scrollTop: 900,
      clientHeight: 100,
    } as HTMLElement
    expect(isNearBottom(el)).toBe(true)
  })

  it('returns false when far from the bottom', () => {
    const el = {
      scrollHeight: 1000,
      scrollTop: 0,
      clientHeight: 100,
    } as HTMLElement
    expect(isNearBottom(el)).toBe(false)
  })
})

describe('stripMemoryForDisplay', () => {
  it('removes leading memory block', () => {
    const raw = '## 已确立的设定决策（务必延续，勿与之矛盾）\n- 主角是剑客\n\n好的，我们来细化世界观。'
    expect(stripMemoryForDisplay(raw)).toBe('好的，我们来细化世界观。')
  })

  it('passes through normal assistant text', () => {
    expect(stripMemoryForDisplay('改好了')).toBe('改好了')
  })
})

describe('resizeTextareaToFit', () => {
  it('grows height with content up to max', () => {
    const el = document.createElement('textarea')
    Object.defineProperty(el, 'scrollHeight', { value: 72, configurable: true })
    resizeTextareaToFit(el)
    expect(el.style.height).toBe('72px')
    expect(el.style.overflowY).toBe('hidden')
  })

  it('caps height and enables scroll when content exceeds max', () => {
    const el = document.createElement('textarea')
    Object.defineProperty(el, 'scrollHeight', { value: 300, configurable: true })
    resizeTextareaToFit(el, 40, 192)
    expect(el.style.height).toBe('192px')
    expect(el.style.overflowY).toBe('auto')
  })
})

describe('reduceChatEvent', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { randomUUID: () => 'test-uuid' })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('appends streaming token to the live assistant message', () => {
    let s: ChatState = { messages: [], live: '', status: '' }
    s = reduceChatEvent(s, { type: 'setup_chat_token', delta: '你好' })
    s = reduceChatEvent(s, { type: 'setup_chat_token', delta: '世界' })
    expect(s.live).toBe('你好世界')
  })

  it('passes through tokens without filtering', () => {
    let s: ChatState = { messages: [], live: '', status: '' }
    s = reduceChatEvent(s, { type: 'setup_chat_token', delta: '{ "logline": "x"' })
    expect(s.live).toBe('{ "logline": "x"')
  })

  it('flushes final message from backend on setup_chat_final', () => {
    let s: ChatState = { messages: [], live: '脏流式内容', status: '' }
    s = reduceChatEvent(s, { type: 'setup_chat_final', content: '改好了' })
    expect(s.live).toBe('')
    expect(s.messages.at(-1)).toEqual({ id: 'test-uuid', role: 'assistant', content: '改好了' })
  })

  it('setup_chat_final 带 thinking 存进消息', () => {
    const s0: ChatState = { messages: [], live: 'x', status: '' }
    const s1 = reduceChatEvent(s0, {
      type: 'setup_chat_final', content: '答案', thinking: '先查一下',
    })
    expect(s1.messages.at(-1)).toMatchObject({ role: 'assistant', content: '答案', thinking: '先查一下' })
    expect(s1.live).toBe('')
  })

  it('setup_chat_final 无 thinking 时消息不带该字段', () => {
    const s0: ChatState = { messages: [], live: '', status: '' }
    const s1 = reduceChatEvent(s0, { type: 'setup_chat_final', content: '答案', thinking: '' })
    expect(s1.messages.at(-1)?.thinking).toBeFalsy()
  })

  it('setup_chat_error appends an assistant bubble with warning prefix', () => {
    const s = reduceChatEvent(EMPTY_CHAT_STATE, { type: 'setup_chat_error', error: 'boom' })
    expect(s.messages.at(-1)).toEqual({ id: 'test-uuid', role: 'assistant', content: '⚠️ boom' })
  })

  it('clears live on done without appending dirty stream', () => {
    let s: ChatState = { messages: [], live: '星黏液简化为粘液', status: '' }
    s = reduceChatEvent(s, { type: 'setup_chat_done' })
    expect(s.live).toBe('')
    expect(s.messages).toEqual([])
  })

  it('renders search progress step and clears on final', () => {
    let s: ChatState = { messages: [], live: '', status: '' }
    s = reduceChatEvent(s, { type: 'setup_chat_tool', name: 'search_research', phase: 'progress', step: 'recall' })
    expect(s.status).toContain('检索')
    s = reduceChatEvent(s, { type: 'setup_chat_final', content: '结果' })
    expect(s.status).toBe('')
  })

  it('ignores tool events', () => {
    let s: ChatState = { messages: [], live: 'x', status: '' }
    s = reduceChatEvent(s, { type: 'setup_chat_tool', name: 'construct_world', phase: 'start' })
    expect(s.live).toBe('x')
  })

  // setup_chat_choice is deliberately not handled by reduceChatEvent -- pendingChoice lives
  // entirely in setupChatSlice's own top-level field (see setupChatPendingChoice.test.ts),
  // already fed by the same wsEventReceived dispatch this reducer's caller uses.
  it('ignores setup_chat_choice (handled by setupChatSlice.pendingChoice instead)', () => {
    const s0: ChatState = { messages: [], live: '', status: '' }
    const s1 = reduceChatEvent(s0, {
      type: 'setup_chat_choice', question: '选哪个？', options: ['甲', '乙'],
    })
    expect(s1).toEqual(s0)
  })

  it('setup_chat_notice appends a system line', () => {
    const s0: ChatState = { messages: [], live: '', status: '' }
    const s1 = reduceChatEvent(s0, {
      type: 'setup_chat_notice', content: '上轮操作已回滚', persist: true,
    })
    expect(s1.messages.at(-1)).toEqual({
      id: 'test-uuid', role: 'system', content: '上轮操作已回滚',
    })
  })
})

// resolveSetupChatMessages/mergeChatMessagesById/applyHistoryRestore all retired -- they existed
// to reconcile local sessionStorage-cached messages against REST history on every mount. Once
// conversation content lives in Redux (setupChatSlice.chat, hydrated once per novel via
// hydrateSetupChat and never destroyed on unmount), there's no local copy left to reconcile with:
// a genuine hydrate is always a fresh novel, mirroring authorLoopSlice/sandboxSlice. Their
// coverage (scope-clear, live-round replay per mode, opening-round content) now lives in
// setupChatSlice.test.ts's "live-chat hydration" describe block.

/** ws/connected/busy/pendingChoice/autoMode all now come from the store instead of props;
 * sendSetupChatMessage/resetSetupChatConversation/onToggleAutoMode are Redux thunks that POST
 * to /api/setup-chat/* under the hood -- assertions that used to check a mock prop was called
 * now check the corresponding fetch call instead. */
// The confirm() toast is normally rendered by a single <Toaster> mounted at the App.tsx level,
// outside this component's own subtree -- mount a local host reading the same useToast()
// singleton alongside the panel so confirm/cancel buttons show up in this test's DOM too.
function ToasterHost() {
  const { toasts, dismiss } = useToast()
  return <><Toaster toasts={toasts} onDismiss={dismiss} /><Sonner /></>
}

function renderPanel(novelId: string, cacheKey: string, preloadedState?: Partial<RootState>) {
  return renderWithProviders(
    <><SetupChatPanel novelId={novelId} cacheKey={cacheKey} /><ToasterHost /></>,
    {
      activeNovelId: novelId,
      preloadedState,
    },
  )
}

/** configureStore's preloadedState replaces a slice's initial state wholesale (no merge), so a
 * test seeding just busy/autoMode/pendingChoice needs the rest of setupChatSlice's shape too --
 * this fills it in. */
function setupChatPreloaded(
  overrides: Partial<{
    busy: boolean
    autoMode: boolean
    pendingChoice: { question: string; options: string[] } | null
    chat: ChatState
    hydratedNovel: string | null
  }>,
) {
  return {
    busy: false, messageQueue: [], autoMode: false, pendingChoice: null, chat: EMPTY_CHAT_STATE,
    hydratedNovel: null, historyLoadedNovel: null, hydrating: false, hydrateEpoch: 0, ...overrides,
  }
}

it('勾选+确认把选中 label 以分点消息发出', async () => {
  renderPanel('default', 'k')
  expect(formatChoiceMessage(['A', 'B'])).toBe('• A\n• B')
  expect(formatChoiceSubmission(['A'], '补充')).toBe('• A\n• 补充')
  expect(allChoiceIndices(3)).toEqual(new Set([0, 1, 2]))
})

describe('present_choices 选项卡', () => {
  beforeEach(() => {
    cleanup()
    sessionStorage.clear()
    vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      if (String(url) === '/api/setup-chat/message' && method === 'POST') {
        return { ok: true, json: async () => ({}) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('可只填补充意见不勾选选项', async () => {
    const { getByPlaceholderText, getByText } = renderPanel('default', 'k:choice-custom', {
      setupChat: setupChatPreloaded({
        pendingChoice: { question: '选哪个？', options: ['甲', '乙'] },
      }),
    })

    fireEvent.change(getByPlaceholderText('或输入自己的意见…'), { target: { value: '我有别的想法' } })
    fireEvent.click(getByText('确认'))

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        '/api/setup-chat/message',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ text: '• 我有别的想法', attachment_ids: [] }),
        }),
      ),
    )
  })

  it('勾选与补充意见一并提交', async () => {
    const { getByText, getByPlaceholderText } = renderPanel('default', 'k:choice-mixed', {
      setupChat: setupChatPreloaded({
        pendingChoice: { question: '选哪个？', options: ['甲', '乙'] },
      }),
    })

    fireEvent.click(getByText('甲'))
    fireEvent.change(getByPlaceholderText('或输入自己的意见…'), { target: { value: '再补充一点' } })
    fireEvent.click(getByText('确认（1）'))

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        '/api/setup-chat/message',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ text: '• 甲\n• 再补充一点', attachment_ids: [] }),
        }),
      ),
    )
  })
})

it('chat.status 非空时气泡内显示转圈动画和状态文案', () => {
  const { getByText } = renderPanel('default', 'k-status', {
    setupChat: setupChatPreloaded({ chat: { ...EMPTY_CHAT_STATE, status: '思考中…' } }),
  })
  const statusEl = getByText('思考中…')
  expect(statusEl.parentElement?.querySelector('svg.animate-spin')).toBeTruthy()
})

describe('清空对话', () => {
  beforeEach(() => {
    cleanup()
    sessionStorage.clear()
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url) === '/api/setup-chat/reset') {
        return { ok: true, json: async () => ({}) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('确认后调用 /api/setup-chat/reset 并清空对话', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url) === '/api/setup-chat/reset') {
        return { ok: true, json: async () => ({}) } as Response
      }
      if (String(url).includes('/api/setup-chat/history')) {
        return {
          ok: true,
          json: async () => ({ messages: [{ id: '1', role: 'user', content: '旧消息' }] }),
        } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    })

    const { getByText, queryByText, findByText } = renderPanel('default', 'k4')
    await waitFor(() => expect(getByText('旧消息')).toBeTruthy())

    await waitFor(() => expect((getByText('清空对话') as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(getByText('清空对话'))
    await findByText(/清空后无法恢复/)
    fireEvent.click(getByText('确定'))

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/setup-chat/reset', { method: 'POST' }))
    await waitFor(() => expect(queryByText('旧消息')).toBeNull())
  })

  it('取消确认时不调用 /api/setup-chat/reset', async () => {
    const { getByText, findByText } = renderPanel('default', 'k5')

    await waitFor(() => expect((getByText('清空对话') as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(getByText('清空对话'))
    await findByText(/清空后无法恢复/)
    fireEvent.click(getByText('取消'))
    expect(fetch).not.toHaveBeenCalledWith('/api/setup-chat/reset', expect.anything())
  })

  it('busy 时清空对话仍禁用，但输入框可继续输入；按钮仅显示中断', async () => {
    const { getByText, getByRole, getByLabelText, queryByLabelText } = renderPanel('default', 'k6', { setupChat: setupChatPreloaded({ busy: true }) })
    expect((getByText('清空对话') as HTMLButtonElement).disabled).toBe(true)
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    expect(getByLabelText('中断')).toBeTruthy()
    expect(queryByLabelText('发送')).toBeNull()
  })
})

describe('auto/manual 切换', () => {
  beforeEach(() => {
    cleanup()
    sessionStorage.clear()
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/api/setup-chat/history')) {
        return { ok: true, json: async () => ({ messages: [] }) } as Response
      }
      if (String(url) === '/api/setup-chat/skills') {
        return { ok: true, json: async () => ({ skills: [] }) } as Response
      }
      if (String(url) === '/api/setup-chat/mode') {
        return { ok: true, json: async () => ({ ok: true, auto: true }) } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('manual 状态下点击切换按钮，POST /api/setup-chat/mode {auto:true}', async () => {
    const { getByText } = renderPanel('default', 'k7')

    await waitFor(() => expect((getByText('切至 AUTO') as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(getByText('切至 AUTO'))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/setup-chat/mode',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ auto: true }) }),
    ))
  })

  it('autoMode=true 时按钮显示已开启状态', () => {
    const { getByText } = renderPanel('default', 'k8', { setupChat: setupChatPreloaded({ autoMode: true }) })
    expect(getByText('AUTO 已开启')).toBeTruthy()
  })

  it('默认（autoMode=false）按钮按 manual 渲染', () => {
    const { getByText } = renderPanel('default', 'k9')
    expect(getByText('切至 AUTO')).toBeTruthy()
  })
})

describe('历史同步 loading 态', () => {
  afterEach(() => { vi.restoreAllMocks(); cleanup() })

  it('history 请求未完成时禁用输入框并显示同步提示', async () => {
    let resolveHistory: (v: Response) => void = () => {}
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/api/setup-chat/history')) {
        return new Promise<Response>((resolve) => { resolveHistory = resolve })
      }
      return { ok: true, json: async () => ({ skills: [] }) } as Response
    })

    const { getByRole, getByText, queryByText } = renderPanel('n1', 'k:n1')

    await waitFor(() => expect(getByText('正在同步对话记录…')).toBeTruthy())
    expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(true)

    resolveHistory({ ok: true, json: async () => ({ messages: [] }) } as Response)

    await waitFor(() => expect(queryByText('正在同步对话记录…')).toBeNull())
    expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false)
  })
})

describe('小说导入进度条：图片识别按张数、文本按分片区分展示', () => {
  afterEach(() => cleanup())

  it('kind=image 时按图片张数展示，文案与文本导入不同', () => {
    const { getByText } = renderPanel('n1', 'k:progress-image', {
      novelImport: { byNovelId: { n1: { status: 'running', kind: 'image', index: 1, total: 3 } } },
    })
    expect(getByText('识别图片中')).toBeTruthy()
    expect(getByText('1/3')).toBeTruthy()
  })

  it('kind=text 时按分片展示，沿用既有文案', () => {
    const { getByText } = renderPanel('n1', 'k:progress-text', {
      novelImport: { byNovelId: { n1: { status: 'running', kind: 'text', index: 37, total: 120 } } },
    })
    expect(getByText('提炼设定中')).toBeTruthy()
    expect(getByText('37/120')).toBeTruthy()
  })
})

describe('斜杠菜单组件行为', () => {
  beforeEach(() => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url) === '/api/setup-chat/skills') {
        return { ok: true, json: async () => ({ skills: [
          { name: 'foreshadowing', description: '伏笔登记', kind: '', source: 'builtin' },
        ] }) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })
  })
  afterEach(() => { vi.restoreAllMocks(); cleanup() })

  it('输入 / 弹菜单，Enter 补全命令而不发送', async () => {
    const { getByRole, getByText, queryByText } = renderPanel('n1', 'k:n1')
    const box = getByRole('textbox')
    fireEvent.change(box, { target: { value: '/' } })
    await waitFor(() => expect(getByText('/foreshadowing')).toBeTruthy())
    fireEvent.keyDown(box, { key: 'Enter' })
    expect((box as HTMLTextAreaElement).value).toBe('/foreshadowing ')
    expect(fetch).not.toHaveBeenCalledWith('/api/setup-chat/message', expect.anything())   // 补全≠发送
    expect(queryByText('伏笔登记')).toBeNull()                    // 出现空格后菜单关闭
  })

  it('非斜杠输入不弹菜单', async () => {
    const { getByRole, queryByText } = renderPanel('n1', 'k:n1')
    fireEvent.change(getByRole('textbox'), { target: { value: '你好' } })
    await waitFor(() => expect(queryByText('/foreshadowing')).toBeNull())
  })

  it('renders history system messages with muted centered style', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url) === '/api/setup-chat/skills') {
        return { ok: true, json: async () => ({ skills: [] }) } as Response
      }
      if (String(url).includes('/api/setup-chat/history')) {
        return {
          ok: true,
          json: async () => ({
            messages: [{
              id: 's-1', role: 'system', content: '已自动补跑完成上轮中断的操作。', seq: 0, ts: 1,
            }],
          }),
        } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })
    const { getByText } = renderPanel('n1', 'k:n1')
    await waitFor(() => expect(getByText('已自动补跑完成上轮中断的操作。')).toBeTruthy())
    const el = getByText('已自动补跑完成上轮中断的操作。')
    expect(el.className).toContain('text-slate-500')
    expect(el.className).toContain('text-center')
  })
})

describe('附件上传与发送', () => {
  afterEach(() => { vi.restoreAllMocks(); cleanup() })

  function mockAttachmentFetch() {
    return vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      const u = String(url)
      if (u === '/api/setup-chat/attachments' && method === 'POST') {
        return { ok: true, json: async () => ({ ok: true, attachment_id: 'att-1', filename: 'novel.txt' }) } as Response
      }
      if (u.startsWith('/api/setup-chat/attachments/') && method === 'DELETE') {
        return { ok: true, json: async () => ({ ok: true }) } as Response
      }
      if (u === '/api/setup-chat/message' && method === 'POST') {
        return { ok: true, json: async () => ({}) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })
  }

  it('选择文件后立即上传并渲染可删除 chip', async () => {
    mockAttachmentFetch()

    const { getByLabelText, getByText } = renderPanel('n1', 'k:attach')
    const file = new File(['正文内容'], 'novel.txt', { type: 'text/plain' })
    const input = getByLabelText('上传附件') as HTMLInputElement
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => expect(getByText('novel.txt')).toBeTruthy())
  })

  it('上传成功后聚焦输入框', async () => {
    mockAttachmentFetch()
    const focusSpy = vi.spyOn(HTMLTextAreaElement.prototype, 'focus')

    const { getByLabelText, getByText } = renderPanel('n1', 'k:attach-focus')
    const file = new File(['正文内容'], 'novel.txt', { type: 'text/plain' })
    fireEvent.change(getByLabelText('上传附件') as HTMLInputElement, { target: { files: [file] } })

    await waitFor(() => expect(getByText('novel.txt')).toBeTruthy())
    await waitFor(() => expect(focusSpy).toHaveBeenCalled())
    focusSpy.mockRestore()
  })

  it('删除 chip 会调用删除接口且不再随发送提交', async () => {
    const fetchMock = mockAttachmentFetch()

    const { getByLabelText, getByText, getByTitle, queryByText } = renderPanel('n1', 'k:attach')
    const file = new File(['正文内容'], 'novel.txt', { type: 'text/plain' })
    fireEvent.change(getByLabelText('上传附件') as HTMLInputElement, { target: { files: [file] } })
    await waitFor(() => expect(getByText('novel.txt')).toBeTruthy())

    fireEvent.click(getByTitle('移除附件'))

    await waitFor(() => expect(queryByText('novel.txt')).toBeNull())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/setup-chat/attachments/att-1',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('清空按钮会移除全部附件 chip 并调用删除接口', async () => {
    const fetchMock = mockAttachmentFetch()

    const { getByLabelText, getByText, getByRole, queryByText } = renderPanel('n1', 'k:attach-clear')
    const file = new File(['正文内容'], 'novel.txt', { type: 'text/plain' })
    fireEvent.change(getByLabelText('上传附件') as HTMLInputElement, { target: { files: [file] } })
    await waitFor(() => expect(getByText('novel.txt')).toBeTruthy())

    fireEvent.click(getByRole('button', { name: '清空' }))

    await waitFor(() => expect(queryByText('novel.txt')).toBeNull())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/setup-chat/attachments/att-1',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('发送消息时把已上传附件的 id 一并提交，随后清空 chip 列表', async () => {
    mockAttachmentFetch()

    const { getByLabelText, getByText, getByRole, queryByText } = renderPanel('n1', 'k:attach')
    const file = new File(['正文内容'], 'novel.txt', { type: 'text/plain' })
    fireEvent.change(getByLabelText('上传附件') as HTMLInputElement, { target: { files: [file] } })
    await waitFor(() => expect(getByText('novel.txt')).toBeTruthy())

    fireEvent.change(getByRole('textbox'), { target: { value: '解析总结小说内容并生成设定' } })
    fireEvent.keyDown(getByRole('textbox'), { key: 'Enter' })

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        '/api/setup-chat/message',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ text: '解析总结小说内容并生成设定', attachment_ids: ['att-1'] }),
        }),
      ),
    )
    await waitFor(() => expect(queryByText('novel.txt')).toBeNull())
  })

  it('只上传附件不输入文字，点发送仍可直接提交（占位文案+附件 id）', async () => {
    mockAttachmentFetch()

    const { getByLabelText, getByText, getByRole, queryByText } = renderPanel('n1', 'k:attach-only')
    const file = new File(['正文内容'], 'novel.txt', { type: 'text/plain' })
    fireEvent.change(getByLabelText('上传附件') as HTMLInputElement, { target: { files: [file] } })
    await waitFor(() => expect(getByText('novel.txt')).toBeTruthy())

    fireEvent.click(getByRole('button', { name: '发送' }))

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        '/api/setup-chat/message',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ text: '[已上传 1 个附件]', attachment_ids: ['att-1'] }),
        }),
      ),
    )
    await waitFor(() => expect(queryByText('novel.txt')).toBeNull())
  })

  it('多选文件按自然文件名顺序上传并提交 attachment_ids', async () => {
    const uploadOrder: string[] = []
    vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      const u = String(url)
      if (u === '/api/setup-chat/attachments' && method === 'POST') {
        const form = init?.body as FormData
        const file = form.get('file') as File
        uploadOrder.push(file.name)
        const id = `att-${file.name}`
        return { ok: true, json: async () => ({ ok: true, attachment_id: id, filename: file.name }) } as Response
      }
      if (u === '/api/setup-chat/message' && method === 'POST') {
        return { ok: true, json: async () => ({}) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })

    const { getByLabelText, getByRole } = renderPanel('n1', 'k:attach-order')
    const files = [
      new File(['c'], '10.jpg'),
      new File(['a'], '1.jpg'),
      new File(['b'], '2.jpg'),
    ]
    fireEvent.change(getByLabelText('上传附件') as HTMLInputElement, { target: { files } })

    await waitFor(() => expect(uploadOrder).toEqual(['1.jpg', '2.jpg', '10.jpg']))

    fireEvent.click(getByRole('button', { name: '发送' }))

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        '/api/setup-chat/message',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            text: '[已上传 3 个附件]',
            attachment_ids: ['att-1.jpg', 'att-2.jpg', 'att-10.jpg'],
          }),
        }),
      ),
    )
  })

  it('既没输入文字也没上传附件时，点发送不提交', async () => {
    const fetchMock = mockAttachmentFetch()

    const { getByRole } = renderPanel('n1', 'k:empty-send')
    fireEvent.click(getByRole('button', { name: '发送' }))

    await new Promise((r) => setTimeout(r, 0))
    expect(fetchMock).not.toHaveBeenCalledWith(
      '/api/setup-chat/message',
      expect.anything(),
    )
  })

  it('上传失败（如类型不支持）时弹出错误提示，不生成 chip', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      if (String(url) === '/api/setup-chat/attachments' && method === 'POST') {
        return { ok: true, json: async () => ({ ok: false, error: '不支持的文件类型' }) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })

    const { getByLabelText, getByText, queryByText } = renderPanel('n1', 'k:attach-fail')
    const file = new File(['abc'], 'novel.pdf', { type: 'application/pdf' })
    fireEvent.change(getByLabelText('上传附件') as HTMLInputElement, { target: { files: [file] } })

    await waitFor(() => expect(getByText('不支持的文件类型')).toBeTruthy())
    expect(queryByText('novel.pdf')).toBeNull()
  })
})

describe('拖拽上传附件', () => {
  afterEach(() => { vi.restoreAllMocks(); cleanup() })

  function mockUploadFetch() {
    return vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      const u = String(url)
      if (u === '/api/setup-chat/attachments' && method === 'POST') {
        return { ok: true, json: async () => ({ ok: true, attachment_id: 'att-1', filename: 'novel.txt' }) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })
  }

  it('拖入携带文件的内容时显示遮罩，拖出后消失', async () => {
    const { getByTestId, getByRole, queryByText } = renderPanel('n1', 'k:drag-1')
    // isSyncing (the history query's isLoading) starts true and keeps the drag handlers'
    // busy||isSyncing guard tripped until it settles -- same wait the interrupt tests already use.
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    const panel = getByTestId('setup-chat-panel')

    fireEvent.dragEnter(panel, { dataTransfer: { types: ['Files'] } })
    expect(queryByText('松开鼠标上传文件到对话')).toBeTruthy()

    fireEvent.dragLeave(panel, { dataTransfer: { types: ['Files'] } })
    expect(queryByText('松开鼠标上传文件到对话')).toBeNull()
  })

  it('拖拽内容不含文件时不显示遮罩', async () => {
    const { getByTestId, getByRole, queryByText } = renderPanel('n1', 'k:drag-2')
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    const panel = getByTestId('setup-chat-panel')

    fireEvent.dragEnter(panel, { dataTransfer: { types: ['text/plain'] } })
    expect(queryByText('松开鼠标上传文件到对话')).toBeNull()
  })

  it('拖拽经过面板内部子元素时遮罩不闪烁（进入计数器抵消冒泡的 enter/leave）', async () => {
    const { getByTestId, getByRole, getByText, queryByText } = renderPanel('n1', 'k:drag-3')
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    const panel = getByTestId('setup-chat-panel')
    // "上传附件" is real rendered text (the label next to the hidden file input) -- unlike the
    // textarea's placeholder attribute, getByText can actually find it. Firing dragEnter/dragLeave
    // on it still bubbles up to the panel root's handlers (only the root has onDragEnter/onDragLeave
    // bound; React events bubble like native ones), which is exactly the "cursor crossed a child
    // element" scenario this test simulates.
    const child = getByText('上传附件')

    fireEvent.dragEnter(panel, { dataTransfer: { types: ['Files'] } })
    fireEvent.dragEnter(child, { dataTransfer: { types: ['Files'] } })
    fireEvent.dragLeave(child, { dataTransfer: { types: ['Files'] } })
    expect(queryByText('松开鼠标上传文件到对话')).toBeTruthy() // still shown, depth is 1 not 0

    fireEvent.dragLeave(panel, { dataTransfer: { types: ['Files'] } })
    expect(queryByText('松开鼠标上传文件到对话')).toBeNull()
  })

  it('drop 后按文件逐个上传，成功的渲染 chip，遮罩消失', async () => {
    mockUploadFetch()
    const { getByTestId, getByRole, getByText, queryByText } = renderPanel('n1', 'k:drag-4')
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    const panel = getByTestId('setup-chat-panel')
    const file = new File(['正文内容'], 'novel.txt', { type: 'text/plain' })

    fireEvent.dragEnter(panel, { dataTransfer: { types: ['Files'] } })
    fireEvent.drop(panel, { dataTransfer: { types: ['Files'], files: [file] } })

    expect(queryByText('松开鼠标上传文件到对话')).toBeNull()
    await waitFor(() => expect(getByText('novel.txt')).toBeTruthy())
  })

  it('忙碌态下仍可拖拽上传', async () => {
    const fetchMock = mockUploadFetch()
    const { getByTestId, getByText, queryByText } = renderPanel(
      'n1', 'k:drag-5', { setupChat: setupChatPreloaded({ busy: true }) },
    )
    await waitFor(() => expect(queryByText('正在同步对话记录…')).toBeNull())
    const panel = getByTestId('setup-chat-panel')
    const file = new File(['正文内容'], 'novel.txt', { type: 'text/plain' })

    fireEvent.dragEnter(panel, { dataTransfer: { types: ['Files'] } })
    fireEvent.drop(panel, { dataTransfer: { types: ['Files'], files: [file] } })

    await waitFor(() => expect(getByText('novel.txt')).toBeTruthy())
    const attachmentCalls = fetchMock.mock.calls.filter(([url]) => String(url) === '/api/setup-chat/attachments')
    expect(attachmentCalls).toHaveLength(1)
  })
})

describe('中断 + 草稿持久化', () => {
  // Same fake-ws shape as StorySandboxPanel.test.tsx's "during opening init" test -- reused
  // here so these interrupt tests can push WS events without a third fake-ws pattern.
  function makeFakeWs() {
    const listeners: Record<string, Array<(e: MessageEvent) => void>> = {}
    const ws = {
      addEventListener: (type: string, fn: (e: MessageEvent) => void) => {
        listeners[type] = listeners[type] ?? []
        listeners[type].push(fn)
      },
      removeEventListener: () => {},
    } as unknown as WebSocket
    const emit = (data: unknown) => {
      for (const fn of listeners.message ?? []) {
        fn({ data: JSON.stringify(data) } as MessageEvent)
      }
    }
    return { ws, emit }
  }

  function mockTurnFetch() {
    return vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      const u = String(url)
      if (u === '/api/setup-chat/message' && method === 'POST') {
        return { ok: true, json: async () => ({}) } as Response
      }
      if (u === '/api/setup-chat/stop' && method === 'POST') {
        return { ok: true, json: async () => ({}) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })
  }

  beforeEach(() => { sessionStorage.clear(); wsHolder.current = null })
  afterEach(() => { vi.restoreAllMocks(); cleanup(); sessionStorage.clear(); wsHolder.current = null })

  it('renders ChatComposerBar (this panel previously had no visible send button at all)', () => {
    mockTurnFetch()
    const { getByLabelText } = renderPanel('n1', 'k:interrupt-render')
    expect(getByLabelText('发送')).toBeTruthy()
  })

  it('sending flips the button to cancel mode, and Escape triggers stopSetupChatTurn (POST /api/setup-chat/stop)', async () => {
    mockTurnFetch()
    const { getByRole, getByLabelText } = renderPanel('n1', 'k:interrupt-escape')
    // Wait for the history/skills queries to settle first -- isSyncing keeps the composer
    // disabled until then, so a click fired too early is a no-op on a disabled button.
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    fireEvent.change(getByRole('textbox'), { target: { value: '继续' } })
    fireEvent.click(getByLabelText('发送'))
    await waitFor(() => expect(getByLabelText('中断')).toBeTruthy())
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => {
      const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls as [string][]
      expect(calls.some(([url]) => url === '/api/setup-chat/stop')).toBe(true)
    })
  })

  it('submitting a message shows the loading spinner bubble immediately, before any tool-progress or token event arrives', async () => {
    mockTurnFetch()
    const { getByRole, getByText, getByLabelText } = renderPanel('n1', 'k:interrupt-spinner')
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    fireEvent.change(getByRole('textbox'), { target: { value: '继续' } })
    fireEvent.click(getByLabelText('发送'))
    const statusEl = getByText('思考中…')
    expect(statusEl.parentElement?.querySelector('svg.animate-spin')).toBeTruthy()
  })

  it('queues a second message locally while busy and auto-POSTs it once the turn finishes', async () => {
    const fetchMock = mockTurnFetch()
    const store = buildTestStore({
      connection: { connected: true },
      setupChat: setupChatPreloaded({ busy: true, hydratedNovel: 'n1', historyLoadedNovel: 'n1' }),
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData(['novels'], [{ id: 'n1', name: 'N', active: true }])
    const { getByRole, getByLabelText, getByText, getByTestId, queryByTestId } = render(
      <Provider store={store}>
        <QueryClientProvider client={client}>
          <SetupChatPanel novelId="n1" cacheKey="k:frontend-queue" />
          <ToasterHost />
        </QueryClientProvider>
      </Provider>,
    )
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    fireEvent.change(getByRole('textbox'), { target: { value: '排队消息' } })
    fireEvent.keyDown(getByRole('textbox'), { key: 'Enter' })

    expect(getByTestId('setup-chat-queue-bar')).toBeTruthy()
    expect(getByText('待发送 (1)')).toBeTruthy()
    expect(getByText('排队消息')).toBeTruthy()
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/setup-chat/message')).toHaveLength(0)

    store.dispatch(wsEventReceived({ type: 'setup_chat_done' } as never))
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/setup-chat/message')).toHaveLength(1)
    })
    await waitFor(() => expect(queryByTestId('setup-chat-queue-bar')).toBeNull())
  })

  it('receiving setup_chat_turn_cancelled restores the submitted text and clears busy', async () => {
    mockTurnFetch()
    const { ws, emit } = makeFakeWs()
    wsHolder.current = ws
    // In production, both the component's own raw ws listener (input-restore/toast, exercised
    // via emit() below) AND wsMiddleware's Redux dispatch of wsEventReceived (busy-clearing, via
    // setupChatSlice's extraReducer) fire for the same incoming message. buildTestStore()
    // deliberately excludes wsMiddleware (see its docstring), so drive the store directly here to
    // reproduce that second consumer instead of only exercising the component-local half.
    const store = buildTestStore({ connection: { connected: true } })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData(['novels'], [{ id: 'n1', name: 'N', active: true }])
    const { getByRole, getByLabelText } = render(
      <Provider store={store}>
        <QueryClientProvider client={client}>
          <SetupChatPanel novelId="n1" cacheKey="k:interrupt-restore" />
          <ToasterHost />
        </QueryClientProvider>
      </Provider>,
    )
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    fireEvent.change(getByRole('textbox'), { target: { value: '被中断的问题' } })
    fireEvent.click(getByLabelText('发送'))
    await waitFor(() => expect(getByLabelText('中断')).toBeTruthy())
    emit({ type: 'setup_chat_turn_cancelled', rollback_failed: false })
    store.dispatch(wsEventReceived({ type: 'setup_chat_turn_cancelled', rollback_failed: false } as never))
    await waitFor(() => expect(getByLabelText('发送')).toBeTruthy())
    expect(getByRole('textbox')).toHaveProperty('value', '被中断的问题')
  })

  it('setup_chat_done invalidates the novels list query (agent-driven rename_novel_title needs the sidebar to refetch)', async () => {
    mockTurnFetch()
    const { ws, emit } = makeFakeWs()
    wsHolder.current = ws
    const store = buildTestStore({ connection: { connected: true } })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData(['novels'], [{ id: 'n1', name: '旧标题', active: true }])
    const { getByRole } = render(
      <Provider store={store}>
        <QueryClientProvider client={client}>
          <SetupChatPanel novelId="n1" cacheKey="k:done-invalidates-novels" />
          <ToasterHost />
        </QueryClientProvider>
      </Provider>,
    )
    await waitFor(() => expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false))
    expect(client.getQueryState(['novels'])?.isInvalidated).toBe(false)
    emit({ type: 'setup_chat_done' })
    await waitFor(() => expect(client.getQueryState(['novels'])?.isInvalidated).toBe(true))
  })

  it('draft persists across novel switch without leaking (the originally-reported bug)', async () => {
    mockTurnFetch()
    const { getByRole, rerender } = renderPanel('novelA', 'setup-chat:novelA')
    fireEvent.change(getByRole('textbox'), { target: { value: 'A的草稿' } })
    await waitFor(() => {
      const raw = sessionStorage.getItem('setup-chat:novelA')
      expect(raw && JSON.parse(raw).draft).toBe('A的草稿')
    })

    rerender(<><SetupChatPanel novelId="novelB" cacheKey="setup-chat:novelB" /><ToasterHost /></>)
    expect(getByRole('textbox')).toHaveProperty('value', '')

    rerender(<><SetupChatPanel novelId="novelA" cacheKey="setup-chat:novelA" /><ToasterHost /></>)
    expect(getByRole('textbox')).toHaveProperty('value', 'A的草稿')
  })

  it('clears attachment chips and deletes server-side ids when switching novels', async () => {
    const deleteCalls: string[] = []
    vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      const u = String(url)
      if (u === '/api/setup-chat/attachments' && method === 'POST') {
        return { ok: true, json: async () => ({ ok: true, attachment_id: 'att-a', filename: 'notes.txt' }) } as Response
      }
      if (u.startsWith('/api/setup-chat/attachments/') && method === 'DELETE') {
        deleteCalls.push(u.split('/').pop() ?? '')
        return { ok: true, json: async () => ({ ok: true }) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })

    const { getByLabelText, getByText, queryByText, rerender } = renderPanel('novelA', 'setup-chat:novelA')
    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' })
    fireEvent.change(getByLabelText('上传附件') as HTMLInputElement, { target: { files: [file] } })
    await waitFor(() => expect(getByText('notes.txt')).toBeTruthy())

    rerender(<><SetupChatPanel novelId="novelB" cacheKey="setup-chat:novelB" /><ToasterHost /></>)
    await waitFor(() => expect(queryByText('notes.txt')).toBeNull())
    expect(deleteCalls).toEqual(['att-a'])
  })

  // The old "events arriving while history is syncing get queued locally and replayed in order
  // after the snapshot lands" guarantee was specific to the retired react-query + local
  // pendingSyncEventsRef design -- see StorySandboxPanel.test.tsx's identical note for the full
  // rationale (live wsEventReceived events now fold into setupChatSlice.chat unconditionally,
  // matching authorLoopSlice/sandboxSlice's own accepted narrow-race characteristic).
})

describe('↑/↓ 翻历史发言', () => {
  afterEach(() => {
    cleanup()
  })

  function seedMessages(...contents: string[]) {
    return {
      ...EMPTY_CHAT_STATE,
      messages: contents.map((content, i) => ({ id: `u${i}`, role: 'user' as const, content })),
    }
  }

  it('聚焦空输入框按 ↑ 两次依次加载最新、次新的用户消息', () => {
    renderPanel('n1', 'k-history-1', {
      setupChat: setupChatPreloaded({
        hydratedNovel: 'n1',
        chat: seedMessages('第一条指令', '第二条指令'),
      }),
    })
    const box = screen.getByRole('textbox') as HTMLTextAreaElement
    box.focus()
    box.setSelectionRange(0, 0)
    fireEvent.keyDown(box, { key: 'ArrowUp' })
    expect(box.value).toBe('第二条指令')
    box.setSelectionRange(box.value.length, box.value.length)
    fireEvent.keyDown(box, { key: 'ArrowUp' })
    expect(box.value).toBe('第一条指令')
  })

  it('slash 菜单激活时按 ↑/↓ 走菜单，不触发历史翻页', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url) === '/api/setup-chat/skills') {
        return { ok: true, json: async () => ({ skills: [
          { name: 'foreshadowing', description: '伏笔登记', kind: '', source: 'builtin' },
        ] }) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })
    renderPanel('n1', 'k-history-2', {
      setupChat: setupChatPreloaded({
        hydratedNovel: 'n1',
        chat: seedMessages('已发过的消息'),
      }),
    })
    const box = screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(box, { target: { value: '/' } })
    await waitFor(() => expect(screen.getByText('/foreshadowing')).toBeTruthy())
    box.setSelectionRange(1, 1)
    fireEvent.keyDown(box, { key: 'ArrowDown' })
    // 菜单接管了这次按键，输入框内容还是 '/'，没有被替换成历史消息
    expect(box.value).toBe('/')
  })
})

describe('regenerate control', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    cleanup()
    sessionStorage.clear()
    fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      const u = String(url)
      if (u === '/api/setup-chat/regenerate' && method === 'POST') {
        return { ok: true, json: async () => ({}) } as Response
      }
      return { ok: true, json: async () => ({ messages: [] }) } as Response
    })
  })

  afterEach(() => {
    cleanup()
    fetchSpy.mockRestore()
    sessionStorage.clear()
  })

  it('shows regenerate on the latest assistant bubble and POSTs the preceding user text', async () => {
    renderPanel('n1', 'k-regen', {
      setupChat: setupChatPreloaded({
        hydratedNovel: 'n1',
        historyLoadedNovel: 'n1',
        chat: {
          messages: [
            { id: 'u1', role: 'user', content: '继续写' },
            { id: 'a1', role: 'assistant', content: '好的，我来写。' },
          ],
          live: '',
          status: '',
        },
      }),
    })
    fireEvent.click(screen.getByRole('button', { name: '重新生成' }))
    await waitFor(() => {
      const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls as [string, RequestInit?][]
      expect(calls.some(([url, init]) => (
        url === '/api/setup-chat/regenerate'
        && init?.method === 'POST'
        && init.body === JSON.stringify({ text: '继续写' })
      ))).toBe(true)
    })
    expect(screen.queryByText('好的，我来写。')).toBeNull()
    expect(screen.getByText('思考中…')).toBeTruthy()
  })

  it('does not show regenerate on non-latest assistant bubbles', () => {
    renderPanel('n1', 'k-regen-no', {
      setupChat: setupChatPreloaded({
        hydratedNovel: 'n1',
        historyLoadedNovel: 'n1',
        chat: {
          messages: [
            { id: 'u1', role: 'user', content: '你好' },
            { id: 'a1', role: 'assistant', content: '在的' },
            { id: 'u2', role: 'user', content: '继续' },
          ],
          live: '',
          status: '',
        },
      }),
    })
    expect(screen.queryByRole('button', { name: '重新生成' })).toBeNull()
  })
})

