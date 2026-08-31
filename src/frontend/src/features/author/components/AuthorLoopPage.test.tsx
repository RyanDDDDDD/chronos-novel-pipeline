import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, cleanup, waitFor, render } from '@testing-library/react'
import { Provider } from 'react-redux'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderWithProviders, buildTestStore } from '@/test/renderWithClient'
import AuthorLoopPage, { agentLabel } from '@/features/author/components/AuthorLoopPage'
import authorLoopReducer from '@/features/author/store/authorLoopSlice'
import { wsEventReceived } from '@/shared/store/wsActions'
import type { AuthorLoopState, AuthorMessage } from '@/shared/types'
import type { RootState } from '@/shared/store/store'

vi.mock('@/shared/utils/archives', () => ({
  fetchArchiveOverview: vi.fn().mockResolvedValue({ built: [], plot_chapters: [] }),
  fetchChapterArchives: vi.fn().mockResolvedValue({ chapter: 2, characters: [] }),
}))

const useAuthorSceneImagesMock = vi.hoisted(() => vi.fn(() => ({ data: {} as Record<string, string> })))
const requestAuthorSceneImageMock = vi.hoisted(() => vi.fn(async () => ({ ok: true })))
vi.mock('@/features/author/queries/sceneImage', () => ({
  useAuthorSceneImages: (...args: unknown[]) => useAuthorSceneImagesMock(...args),
  requestAuthorSceneImage: (...args: unknown[]) => requestAuthorSceneImageMock(...args),
}))

const toastErrorMock = vi.hoisted(() => vi.fn())
vi.mock('@/shared/hooks/useToast', () => ({
  useToast: () => ({ error: toastErrorMock, success: vi.fn(), confirm: vi.fn(), prompt: vi.fn(), toasts: [], dismiss: vi.fn() }),
}))

beforeEach(() => {
  cleanup()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes('/api/chapters') ? { chapters: [{ chapter: 1 }, { chapter: 2 }, { chapter: 3 }] } : {},
  })) as unknown as typeof fetch)
  useAuthorSceneImagesMock.mockReset().mockReturnValue({ data: {} })
  requestAuthorSceneImageMock.mockReset().mockResolvedValue({ ok: true })
  toastErrorMock.mockReset()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const idle: AuthorLoopState = { status: 'idle', chapter: 0, total: 0, messages: [] }

function segMsg(index: number, text: string, extra: Partial<{ skill: string | null; intent: string; draft: boolean }> = {}): AuthorMessage {
  return { id: `seg-${index}`, role: 'agent', type: 'segment', segment: { index, intent: extra.intent ?? '', skill: extra.skill ?? null, text, draft: extra.draft } }
}

/** AuthorLoopPage now self-selects everything from the store (chapter fixed at 2 to match the
 * old hard-coded prop tests below); resumable is expressed via resumableChapters containing 2. */
function preloadedStateFor(authorLoop: AuthorLoopState, opts: { resumable?: boolean } = {}): Partial<RootState> {
  const base = authorLoopReducer(undefined, { type: '@@INIT' })
  return {
    ui: { chapter: 2, setupTab: 'world' },
    authorLoop: { ...base, ...authorLoop, resumableChapters: opts.resumable ? [2] : [] },
  }
}

function renderPage(authorLoop: AuthorLoopState, opts: { resumable?: boolean } = {}) {
  return renderWithProviders(
    <MemoryRouter initialEntries={['/novel/default/author']}>
      <AuthorLoopPage />
    </MemoryRouter>,
    { preloadedState: preloadedStateFor(authorLoop, opts) },
  )
}

/** Exposes the underlying store (unlike renderWithProviders) so tests can dispatch follow-up WS
 * events to simulate a live-updating timeline -- mirrors the App-level test files' own pattern
 * (buildTestStore + <Provider>) for the same "need the store reference" reason. */
function renderLoopHarness(initial: AuthorLoopState) {
  const store = buildTestStore(preloadedStateFor(initial))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['novels'], [{ id: 'default', name: 'N', active: true }])
  const utils = render(
    <Provider store={store}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/novel/default/author']}>
          <AuthorLoopPage />
        </MemoryRouter>
      </QueryClientProvider>
    </Provider>,
  )
  return { ...utils, store }
}

function mockScrollContainer() {
  const container = document.querySelector('.overflow-y-auto') as HTMLElement
  Object.defineProperty(container, 'scrollHeight', { value: 2000, configurable: true })
  Object.defineProperty(container, 'clientHeight', { value: 500, configurable: true })
  Object.defineProperty(container, 'scrollTop', { value: 1500, writable: true, configurable: true })
  return container
}

describe('agentLabel', () => {
  it('director/character/synthesis → 中文标注', () => {
    expect(agentLabel('director')).toBe('导演·旁白')
    expect(agentLabel('character', '爱丽丝')).toBe('角色·爱丽丝')
    expect(agentLabel('synthesis')).toBe('合成·正文')
  })
  it('无 agent → 空串', () => {
    expect(agentLabel(undefined)).toBe('')
  })
})

function dialogueLoop(): AuthorLoopState {
  return {
    status: 'running', chapter: 2, total: 1,
    messages: [
      { id: 's0', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '旁白内容。', agent: 'director' } },
      { id: 's1', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '角色台词内容。', agent: 'character', role: '甲' } },
      { id: 's2', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '合成正文内容。', agent: 'synthesis' } },
      { id: 'st', role: 'agent', type: 'state', characters: [{
        name: '甲', psychology: '紧张', posture: '', clothing: '', action: '攥紧衣角', demeanor: '低头',
      }] },
      { id: 'sum', role: 'agent', type: 'summary', text: '摘要内容。' },
    ],
  }
}

describe('AuthorLoopPage 标签过滤', () => {
  it('对话模式有标签消息 → 显示过滤栏（5 类 chip）', () => {
    renderPage(dialogueLoop())
    expect(screen.getByRole('button', { name: '导演' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '角色表演' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '合成正文' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '角色状态' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '摘要' })).toBeTruthy()
  })

  it('默认全显示；点 chip 隐藏该类，其它类保留', () => {
    renderPage(dialogueLoop())
    expect(screen.getByText('角色台词内容。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '角色表演' }))
    expect(screen.queryByText('角色台词内容。')).toBeNull()   //Character segment is hidden
    expect(screen.getByText('旁白内容。')).toBeTruthy()        //Director's section reserved
    expect(screen.getByText('合成正文内容。')).toBeTruthy()    //Synthesis section reserved
    expect(screen.getByText('摘要内容。')).toBeTruthy()        //Summary reserved
  })

  it('再点同一 chip → 恢复显示', () => {
    renderPage(dialogueLoop())
    const chip = screen.getByRole('button', { name: '摘要' })
    fireEvent.click(chip)
    expect(screen.queryByText('摘要内容。')).toBeNull()
    fireEvent.click(chip)
    expect(screen.getByText('摘要内容。')).toBeTruthy()
  })

  it('过滤同样作用于 live 流式气泡', () => {
    renderPage({
      status: 'running', chapter: 2, total: 1,
      messages: [{ id: 's0', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '已定稿旁白。', agent: 'director' } }],
      live: [{ agent: 'synthesis', text: '正文流式生成中…' }],
    })
    expect(screen.getByText('正文流式生成中…')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '合成正文' }))
    expect(screen.queryByText('正文流式生成中…')).toBeNull()  //live compositions are also filtered
  })

  it('无标签段（非对话模式）→ 不显示过滤栏', () => {
    renderPage({ status: 'running', chapter: 2, total: 1, messages: [segMsg(0, '纯叙事段。')] })
    expect(screen.queryByRole('button', { name: '导演' })).toBeNull()
  })

  it('StateBubble 渲染心理/体态/着装/动作/神态五个字段', () => {
    renderPage(dialogueLoop())
    fireEvent.click(screen.getByText(/🧬 角色状态/))
    expect(screen.getByText(/心理：紧张/)).toBeTruthy()
    expect(screen.getByText(/动作：攥紧衣角/)).toBeTruthy()
    expect(screen.getByText(/神态：低头/)).toBeTruthy()
    expect(screen.queryByText(/沦陷/)).toBeNull()
  })

  it('同一 beat 的 event_log/recall/state 合并在一个 agent bubble 内', () => {
    renderPage({
      status: 'running', chapter: 2, total: 1,
      messages: [
        { id: 'seg-0-recall', role: 'agent', type: 'recall', recallContext: '## 相关历史/设定回收\n- 第2章：旧账未清' },
        { id: 'seg-0-state', role: 'agent', type: 'state', characters: [{
          name: '甲', psychology: '紧张', posture: '', clothing: '', action: '攥紧衣角', demeanor: '低头',
        }] },
        { id: 'seg-0-event_log', role: 'agent', type: 'event_log', events: [{
          summary: '甲把玉佩交给了乙', time: '决战之后', location: '藏经阁', characters: ['甲', '乙'],
        }] },
      ],
    })
    expect(screen.getByText(/🕮 记忆归档/)).toBeTruthy()
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.getByText(/甲把玉佩交给了乙/)).toBeTruthy()
    expect(screen.getByText(/🔍 记忆召回/)).toBeTruthy()
    fireEvent.click(screen.getByText(/🔍 记忆召回/))
    expect(screen.getByText(/旧账未清/)).toBeTruthy()
    fireEvent.click(screen.getByText(/🧬 角色状态/))
    expect(screen.getByText(/心理：紧张/)).toBeTruthy()
    const archiveSummary = screen.getByText(/🕮 记忆归档/)
    const sharedBubble = archiveSummary.closest('.max-w-\\[85\\%\\]')
    expect(sharedBubble?.textContent).toContain('记忆召回')
    expect(sharedBubble?.textContent).toContain('心理：紧张')
  })

  it('同一 beat 的多条记忆归档聚合进一个气泡', () => {
    renderPage({
      status: 'running', chapter: 2, total: 1,
      messages: [
        { id: 'seg-0-event_log', role: 'agent', type: 'event_log', events: [
          { summary: '甲推开门', time: '深夜' },
          { summary: '乙想起童年', time: '十年前' },
        ] },
      ],
    })
    expect(screen.getAllByText(/🕮 记忆归档/)).toHaveLength(1)
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.getByText(/甲推开门/)).toBeTruthy()
    expect(screen.getByText(/乙想起童年/)).toBeTruthy()
  })
})

describe('AuthorLoopPage', () => {
  it('idle 态显示空提示，点运行用选中章节触发 /api/author-loop/start', async () => {
    renderPage(idle)
    expect(screen.getByText(/选择章节后点击/)).toBeTruthy()
    fireEvent.click(screen.getByText('运行主笔'))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/author-loop/start',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ chapter: 2 }) }),
    ))
  })

  it('主笔页展示成稿入口按钮', () => {
    renderPage(idle)
    expect(screen.getByRole('button', { name: '成稿' })).toBeTruthy()
  })

  it('shows resume/restart buttons when chapter is resumable', () => {
    renderPage(idle, { resumable: true })
    expect(screen.getByText('继续')).toBeTruthy()
    expect(screen.getByText('重新开始')).toBeTruthy()
  })

  it('继续 triggers /api/author-loop/resume with the current chapter', async () => {
    renderPage(idle, { resumable: true })
    fireEvent.click(screen.getByText('继续'))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/author-loop/resume',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ chapter: 2 }) }),
    ))
  })

  it('重新开始 triggers /api/author-loop/start with fresh:true', async () => {
    renderPage(idle, { resumable: true })
    fireEvent.click(screen.getByText('重新开始'))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/author-loop/start',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ chapter: 2, fresh: true }) }),
    ))
  })

  it('时间线逐段渲染为 agent 气泡（正文 + agent 标注）', () => {
    renderPage({
      status: 'running', chapter: 2, total: 2,
      messages: [
        { id: 'seg-0', role: 'agent', type: 'segment', segment: { index: 0, intent: '查案', skill: null, text: '主角推门而入。', agent: 'director' } },
        { id: 'seg-1', role: 'agent', type: 'segment', segment: { index: 1, intent: '亲密', skill: 'position', text: '两人交缠。', agent: 'character', role: '爱丽丝' } },
      ],
    })
    expect(screen.getByText('主角推门而入。')).toBeTruthy()
    expect(screen.getByText('两人交缠。')).toBeTruthy()
    expect(screen.getByText('导演·旁白')).toBeTruthy()
    expect(screen.getByText('角色·爱丽丝')).toBeTruthy()
  })

  it('角色表演气泡显示动作意图、心理活动与台词', () => {
    renderPage({
      status: 'running', chapter: 2, total: 1,
      messages: [
        { id: 'seg-0', role: 'agent', type: 'segment', segment: {
          index: 0, intent: '伸手按住对方肩膀', psychology: '心虚却强撑',
          skill: null, text: '舒服……说不清楚……', agent: 'character', role: '柚子',
        } },
      ],
    })
    expect(screen.getByText('💃 动作意图：')).toBeTruthy()
    expect(screen.getByText(/伸手按住对方肩膀/)).toBeTruthy()
    expect(screen.getByText('🧠 心理活动：')).toBeTruthy()
    expect(screen.getByText(/心虚却强撑/)).toBeTruthy()
    expect(screen.getByText('💬 台词')).toBeTruthy()
    expect(screen.getByText('舒服……说不清楚……')).toBeTruthy()
  })

  it('写作中指示按段/节聚合：第 X 段 · 第 Y/T 节 ／ 共 N 段', () => {
    renderPage({
      status: 'running', chapter: 2, total: 3,
      messages: [
        { id: 'seg-0-beat-0', role: 'agent', type: 'segment', segment: { index: 0, beat: 0, beats: 2, intent: '', skill: null, text: 'a' } },
        { id: 'seg-1-beat-1', role: 'agent', type: 'segment', segment: { index: 1, beat: 1, beats: 3, intent: '', skill: null, text: 'b' } },
      ],
    })
    //Get the last beat message: Section 2 · Section 2/3 / 3 sections in total (beat count is no longer the number of sections)
    expect(screen.getByText(/第 2 段 · 第 2\/3 节/)).toBeTruthy()
    expect(screen.getByText(/共 3 段/)).toBeTruthy()
  })

  it('beat 气泡：单段切多 beat 时标「第 N 段 · beat M/T」', () => {
    renderPage({
      status: 'running', chapter: 2, total: 1,
      messages: [
        { id: 'seg-0-beat-0', role: 'agent', type: 'segment', segment: { index: 0, beat: 0, beats: 3, intent: '', skill: null, text: '铺垫。' } },
        { id: 'seg-0-beat-2', role: 'agent', type: 'segment', segment: { index: 0, beat: 2, beats: 3, intent: '', skill: 'position', text: '高潮。' } },
      ],
    })
    expect(screen.getByText('第 1 段 · beat 1/3')).toBeTruthy()
    expect(screen.getByText('第 1 段 · beat 3/3')).toBeTruthy()
  })

  it('error 态显示错误信息', () => {
    renderPage({ ...idle, status: 'error', error: '主笔写作失败' })
    expect(screen.getByText('主笔写作失败')).toBeTruthy()
  })

  it('done 态不显示手动保存按钮', () => {
    renderPage(
      { status: 'done', chapter: 2, total: 1, messages: [segMsg(0, '正文。')] },
    )
    expect(screen.queryByText('保存')).toBeNull()
    expect(screen.getByText(/写作完成/)).toBeTruthy()
  })

  it('整章进度条：显示 done/total + 百分比', () => {
    renderPage({
      status: 'running', chapter: 3, total: 0, messages: [],
      chapterProgress: { done: 2, total: 8 },
    })
    expect(screen.getByText(/第3章 创作进度/)).toBeTruthy()
    expect(screen.getByText(/2\/8 段 · 25%/)).toBeTruthy()
  })

  it('流式 live 气泡：各 agent 输出并存、不互相冲掉', () => {
    renderPage({
      status: 'running', chapter: 2, total: 2, messages: [],
      live: [
        { agent: 'director', text: '旁白先到。' },
        { agent: 'synthesis', text: '正文随后一句句生成…' },
      ],
    })
    expect(screen.getByText('旁白先到。')).toBeTruthy()       //The previous one is still there
    expect(screen.getByText('正文随后一句句生成…')).toBeTruthy()
    expect(screen.getByText(/导演·旁白/)).toBeTruthy()
    expect(screen.getByText(/合成·正文/)).toBeTruthy()
  })

  it('流式 live：角色 JSON 增量解析为结构化字段（不裸显 JSON）', () => {
    renderPage({
      status: 'running', chapter: 2, total: 1, messages: [],
      live: [{ agent: 'character', role: '柚子', text: '{"dialogue":"你好","intent":"扬手' }],
    })
    expect(screen.getByText('💬 台词')).toBeTruthy()
    expect(screen.getByText('你好')).toBeTruthy()
    expect(screen.getByText(/扬手/)).toBeTruthy()
    expect(screen.queryByText(/\{"dialogue"/)).toBeNull()
  })

  it('定稿长段默认折叠，点「展开全文」看全文、再点「收起」', () => {
    const longText = '甲'.repeat(500)
    renderPage({
      status: 'done', chapter: 2, total: 1,
      messages: [segMsg(0, longText)],  //Finalized (no draft)
    })
    const btn = screen.getByText(/展开全文（500 字）/)
    expect(btn).toBeTruthy()                 //Long paragraphs have expand buttons
    fireEvent.click(btn)
    expect(screen.getByText('收起')).toBeTruthy()  //Expand and then collapse
  })

  it('草稿长段默认折叠，点「展开全文」后显示收起', () => {
    renderPage({
      status: 'running', chapter: 2, total: 1,
      messages: [segMsg(0, '乙'.repeat(500), { draft: true })],
    })
    const btn = screen.getByText(/展开全文（500 字）/)
    expect(btn).toBeTruthy()
    fireEvent.click(btn)
    expect(screen.getByText('收起')).toBeTruthy()
  })

  it('短段无展开按钮', () => {
    renderPage({
      status: 'done', chapter: 2, total: 1,
      messages: [segMsg(0, '短短一段。')],
    })
    expect(screen.queryByText(/展开全文/)).toBeNull()
  })

  it('running 态：按钮切为「停止」，点击触发 /api/author-loop/stop', async () => {
    renderPage({ status: 'running', chapter: 2, total: 1, messages: [] })
    expect(screen.queryByText('运行主笔')).toBeNull()  //"Run Main" is not displayed during running
    fireEvent.click(screen.getByText('停止'))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/author-loop/stop', { method: 'POST' }))
  })

  describe('滚动跟随', () => {
    let scrollTo: ReturnType<typeof vi.fn>

    beforeEach(() => {
      scrollTo = vi.fn()
      HTMLElement.prototype.scrollTo = scrollTo
    })

    afterEach(() => {
      delete (HTMLElement.prototype as { scrollTo?: typeof scrollTo }).scrollTo
    })

    it('用户在底部附近时，新段正文仍会跟随滚到底', async () => {
      const initial: AuthorLoopState = {
        status: 'running', chapter: 2, total: 2,
        messages: [segMsg(0, '第一段。')],
      }
      const { store } = renderLoopHarness(initial)
      mockScrollContainer()
      await waitFor(() => expect(scrollTo).toHaveBeenCalled())
      scrollTo.mockClear()
      store.dispatch(wsEventReceived({ type: 'author_loop_segment', index: 1, intent: '', skill: null, text: '第二段。', total: 2 }))
      await waitFor(() => expect(scrollTo).toHaveBeenCalled())
    })

    it('用户上滑浏览前文时，新段/正文增量不自动滚到底', async () => {
      const initial: AuthorLoopState = {
        status: 'running', chapter: 2, total: 1,
        messages: [segMsg(0, '第一段。')],
      }
      const { store } = renderLoopHarness(initial)
      const container = mockScrollContainer()
      await waitFor(() => expect(scrollTo).toHaveBeenCalled())
      scrollTo.mockClear()
      container.scrollTop = 0
      fireEvent.scroll(container)
      store.dispatch(wsEventReceived({ type: 'author_loop_segment', index: 1, intent: '', skill: null, text: '第二段。', total: 1 }))
      await waitFor(() => expect(screen.getByText('第二段。')).toBeTruthy())
      expect(scrollTo).not.toHaveBeenCalled()
    })

    it('用户上滑浏览前文时，末段原地扩写不自动滚到底', async () => {
      const initial: AuthorLoopState = {
        status: 'running', chapter: 2, total: 1,
        messages: [segMsg(0, '短草稿。', { draft: true })],
      }
      const { store } = renderLoopHarness(initial)
      const container = mockScrollContainer()
      await waitFor(() => expect(scrollTo).toHaveBeenCalled())
      scrollTo.mockClear()
      container.scrollTop = 0
      fireEvent.scroll(container)
      store.dispatch(wsEventReceived({
        type: 'author_loop_segment', index: 0, intent: '', skill: null,
        text: '短草稿。' + '扩'.repeat(400), draft: true, total: 1,
      }))
      await waitFor(() => expect(screen.getByText(/展开全文/)).toBeTruthy())
      expect(scrollTo).not.toHaveBeenCalled()
    })
  })
})

describe('AuthorLoopPage 场景生图', () => {
  it('renders a scene-image row on synthesis segments', () => {
    renderPage({
      status: 'done', chapter: 2, total: 1,
      messages: [{ id: 'seg-0', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '正文内容。', agent: 'synthesis' } }],
    })
    expect(screen.getByRole('button', { name: /生图/ })).toBeTruthy()
  })

  it('does not render a scene-image row on non-synthesis / empty-text segments', () => {
    renderPage({
      status: 'done', chapter: 2, total: 2,
      messages: [
        { id: 'seg-0', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '旁白内容。', agent: 'director' } },
        { id: 'seg-1', role: 'agent', type: 'segment', segment: { index: 1, intent: '', skill: null, text: '', agent: 'synthesis' } },
      ],
    })
    expect(screen.queryByRole('button', { name: /生图/ })).toBeNull()
  })

  it('does not render a scene-image row when the synthesis prose renders empty', () => {
    renderPage({
      status: 'done', chapter: 2, total: 1,
      messages: [{ id: 'seg-0', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '# 合成正文\n   \n', agent: 'synthesis' } }],
    })
    expect(screen.queryByRole('button', { name: /生图/ })).toBeNull()
  })

  it('shows the existing image when the map has this stage index', () => {
    useAuthorSceneImagesMock.mockReturnValue({ data: { '0': '/api/author-loop/scene-image/6/0/file?v=x' } })
    renderPage({
      status: 'done', chapter: 2, total: 1,
      messages: [{ id: 'seg-0', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '正文内容。', agent: 'synthesis' } }],
    })
    expect(screen.getByRole('img').getAttribute('src')).toBe('/api/author-loop/scene-image/6/0/file?v=x')
  })

  it('生图 button triggers requestAuthorSceneImage with the current chapter + segment index', async () => {
    renderPage({
      status: 'done', chapter: 2, total: 1,
      messages: [{ id: 'seg-0', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '正文内容。', agent: 'synthesis' } }],
    })
    fireEvent.click(screen.getByRole('button', { name: /生图/ }))
    await waitFor(() => expect(requestAuthorSceneImageMock).toHaveBeenCalledWith(2, 0))
  })

  it('shows a toast when the generate request itself fails', async () => {
    requestAuthorSceneImageMock.mockResolvedValueOnce({ ok: false })
    renderPage({
      status: 'done', chapter: 2, total: 1,
      messages: [{ id: 'seg-0', role: 'agent', type: 'segment', segment: { index: 0, intent: '', skill: null, text: '正文内容。', agent: 'synthesis' } }],
    })
    fireEvent.click(screen.getByRole('button', { name: /生图/ }))
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledWith('场景生图请求失败，请重试'))
  })

  it('toasts and consumes a scene-image failure broadcast from the store', async () => {
    const { store } = renderLoopHarness({
      status: 'done', chapter: 2, total: 1,
      messages: [segMsg(0, '正文内容。')],
    })
    store.dispatch(wsEventReceived({ type: 'author_scene_image_started', novel_id: 'default', chapter: 2, index: 0 }))
    store.dispatch(wsEventReceived({ type: 'author_scene_image_done', novel_id: 'default', chapter: 2, index: 0, error: '未配置模型' }))
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledWith('场景生图失败：未配置模型'))
    expect(store.getState().authorSceneImage.lastFailure).toBeNull()
  })

  it('does not toast a failure belonging to a chapter the page is not showing', async () => {
    const { store } = renderLoopHarness({
      status: 'done', chapter: 2, total: 1,
      messages: [segMsg(0, '正文内容。')],
    })
    store.dispatch(wsEventReceived({ type: 'author_scene_image_done', novel_id: 'default', chapter: 9, index: 0, error: '未配置模型' }))
    await waitFor(() => expect(store.getState().authorSceneImage.lastFailure).toBeNull())
    expect(toastErrorMock).not.toHaveBeenCalled()
  })
})
