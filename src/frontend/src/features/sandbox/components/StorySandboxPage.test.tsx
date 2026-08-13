/** @vitest-environment jsdom */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithClient'
import StorySandboxPage from '@/features/sandbox/components/StorySandboxPage'

vi.mock('@/features/sandbox/components/StorySandboxPanel', () => ({
  default: ({
    characterNames, settingNames, selectedMemories, onRemoveMemory, onClearMemories,
  }: {
    characterNames?: string[]
    settingNames?: string[]
    selectedMemories?: { id: string; summary: string }[]
    onRemoveMemory?: (id: string) => void
    onClearMemories?: () => void
  }) => (
    <div data-testid="sandbox-panel">
      <span data-testid="character-names">{(characterNames ?? []).join(',')}</span>
      <span data-testid="setting-names">{(settingNames ?? []).join(',')}</span>
      <span data-testid="selected-memories">{(selectedMemories ?? []).map((m) => m.id).join(',')}</span>
      <button type="button" onClick={() => onRemoveMemory?.('mem-1')}>panel-remove-memory</button>
      <button type="button" onClick={() => onClearMemories?.()}>panel-clear-memories</button>
    </div>
  ),
}))

const useSandboxActiveCastMock = vi.hoisted(() => vi.fn(() => ['甲', '乙']))

const useCastMock = vi.hoisted(() => vi.fn(() => ({ data: [{ name: '甲' }, { name: '乙' }] })))
const useWorldMock = vi.hoisted(() => vi.fn(() => ({ data: undefined })))

vi.mock('@/shared/queries/setup', () => ({
  useCast: () => useCastMock(),
  useWorld: () => useWorldMock(),
}))

vi.mock('@/features/sandbox/components/SandboxCharacterPanel', () => ({
  default: ({
    chapter, activeCast, branchId, selectedMemoryIds, onToggleMemory,
  }: {
    chapter: number
    activeCast: string[]
    branchId?: string | null
    selectedMemoryIds?: Set<string>
    onToggleMemory?: (entry: { id: string; summary: string }) => void
  }) => (
    <aside data-testid="cast-panel" data-chapter={chapter} data-branch-id={branchId ?? ''}>
      <span data-testid="active-cast">{activeCast.join(',')}</span>
      <span data-testid="selected-memory-ids">{[...(selectedMemoryIds ?? [])].join(',')}</span>
      <button type="button" onClick={() => onToggleMemory?.({ id: 'mem-1', summary: '旧事件' })}>
        panel-toggle-memory
      </button>
    </aside>
  ),
}))

vi.mock('@/features/sandbox/hooks/useSandboxActiveCast', () => ({
  useSandboxActiveCast: (...args: unknown[]) => useSandboxActiveCastMock(...args),
}))

vi.mock('@/features/sandbox/hooks/useStorySandbox', () => ({
  useStorySandbox: () => ({
    sendMessage: vi.fn(),
    stopTurn: vi.fn(),
    regenerateSuggestions: vi.fn(),
    startRewrite: vi.fn(),
    rewriteSelection: vi.fn(),
  }),
}))

function mockChapterList(chapters: number[] = [1, 2]) {
  vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
    if (String(url).includes('/api/chapters')) {
      return {
        ok: true,
        json: async () => ({ chapters: chapters.map((chapter) => ({ chapter })) }),
      } as Response
    }
    return { ok: true, json: async () => ({}) } as Response
  })
}

// Native jsdom localStorage isn't reliable under this project's Vitest/Node setup (its .clear
// is undefined) -- same workaround theme.test.ts already uses. sessionStorage works natively,
// no stub needed for it.
function mockLocalStorage() {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
    clear: () => { store.clear() },
  })
}

describe('StorySandboxPage', () => {
  beforeEach(() => {
    mockChapterList()
    mockLocalStorage()
    sessionStorage.clear()
    useSandboxActiveCastMock.mockClear()
    useCastMock.mockClear()
    useWorldMock.mockClear()
    useWorldMock.mockReturnValue({ data: undefined })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders sandbox panel and cast panel side by side', async () => {
    localStorage.setItem('story-sandbox-mode:novel-1', 'chapter')
    renderWithProviders(<StorySandboxPage />, {
      activeNovelId: 'novel-1',
      preloadedState: { ui: { chapter: 1 } },
    })
    expect(await screen.findByText('故事沙盒')).toBeTruthy()
    expect(screen.getByTestId('sandbox-panel')).toBeTruthy()
    expect(screen.getByTestId('active-cast').textContent).toBe('甲,乙')
    expect(useSandboxActiveCastMock).toHaveBeenCalledWith('novel-1', 1, '')
    expect(screen.getByTestId('cast-panel').getAttribute('data-chapter')).toBe('1')
  })

  it('free mode passes chapter 0 to cast hook and panel', async () => {
    localStorage.setItem('story-sandbox-mode:novel-1', 'free')
    renderWithProviders(<StorySandboxPage />, {
      activeNovelId: 'novel-1',
      preloadedState: { ui: { chapter: 3 } },
    })
    await waitFor(() => {
      expect(useSandboxActiveCastMock).toHaveBeenLastCalledWith('novel-1', 0, '')
    })
    expect(screen.getByTestId('cast-panel').getAttribute('data-chapter')).toBe('0')
  })

  it('mode 持久化用 localStorage 而非 sessionStorage，重启应用（新会话）后仍保留', async () => {
    sessionStorage.setItem('story-sandbox-mode:novel-1', 'chapter')
    localStorage.setItem('story-sandbox-mode:novel-1', 'free')
    renderWithProviders(<StorySandboxPage />, {
      activeNovelId: 'novel-1',
      preloadedState: { ui: { chapter: 3 } },
    })
    await waitFor(() => {
      expect(useSandboxActiveCastMock).toHaveBeenLastCalledWith('novel-1', 0, '')
    })
    expect(screen.getByTestId('cast-panel').getAttribute('data-chapter')).toBe('0')
  })

  it('把 useCast() 的角色名单传给 StorySandboxPanel 的 characterNames', async () => {
    localStorage.setItem('story-sandbox-mode:novel-1', 'chapter')
    renderWithProviders(<StorySandboxPage />, {
      activeNovelId: 'novel-1',
      preloadedState: { ui: { chapter: 1 } },
    })
    expect(await screen.findByText('故事沙盒')).toBeTruthy()
    expect(screen.getByTestId('character-names').textContent).toBe('甲,乙')
  })

  it('把 useWorld() 的 factions/geography/races/power_system 名称合并传给 settingNames（不含 core_themes）', async () => {
    useWorldMock.mockReturnValue({
      data: {
        world_bible: {
          factions: [{ name: '门派A', desc: '' }],
          geography: [{ name: '城市B', desc: '' }],
          races: [{ name: '种族C', desc: '' }],
          power_system: [{ name: '元气', desc: '' }],
          core_themes: [{ name: '复仇', desc: '' }],
        },
      },
    })
    localStorage.setItem('story-sandbox-mode:novel-1', 'chapter')
    renderWithProviders(<StorySandboxPage />, {
      activeNovelId: 'novel-1',
      preloadedState: { ui: { chapter: 1 } },
    })
    expect(await screen.findByText('故事沙盒')).toBeTruthy()
    const settingNames = screen.getByTestId('setting-names').textContent ?? ''
    expect(settingNames).toContain('门派A')
    expect(settingNames).toContain('城市B')
    expect(settingNames).toContain('种族C')
    expect(settingNames).toContain('元气')
    expect(settingNames).not.toContain('复仇')
  })

  it('回归：power_system 仍是未迁移的旧格式（自由文本字符串）时不崩溃，且不贡献任何 settingNames', async () => {
    useWorldMock.mockReturnValue({
      data: {
        world_bible: {
          factions: [{ name: '天音寺', desc: '' }],
          power_system: '远古秘术锻体所得的「玄脉」，需长期修炼方能激活',
          core_themes: ['复仇', '成长'],
        },
      },
    })
    localStorage.setItem('story-sandbox-mode:novel-1', 'chapter')
    renderWithProviders(<StorySandboxPage />, {
      activeNovelId: 'novel-1',
      preloadedState: { ui: { chapter: 1 } },
    })
    expect(await screen.findByText('故事沙盒')).toBeTruthy()
    // Exact match matters here: a pre-fix build would spread the legacy string character-by-
    // character and map each char to `undefined`, which Array.prototype.join renders as empty
    // segments -- e.g. "天音寺,,,,,,,,,..." -- so a loose .toContain assertion wouldn't catch it.
    expect(screen.getByTestId('setting-names').textContent).toBe('天音寺')
  })

  it('点击右侧面板的记忆条目后，选中集合同步到两边；点击面板按钮可移除/清空', async () => {
    localStorage.setItem('story-sandbox-mode:novel-1', 'chapter')
    renderWithProviders(<StorySandboxPage />, {
      activeNovelId: 'novel-1',
      preloadedState: { ui: { chapter: 1 } },
    })
    await screen.findByText('故事沙盒')

    expect(screen.getByTestId('selected-memories').textContent).toBe('')
    expect(screen.getByTestId('selected-memory-ids').textContent).toBe('')

    fireEvent.click(screen.getByText('panel-toggle-memory'))
    await waitFor(() => expect(screen.getByTestId('selected-memories').textContent).toBe('mem-1'))
    expect(screen.getByTestId('selected-memory-ids').textContent).toBe('mem-1')

    // 再点一次 SandboxCharacterPanel 侧的 toggle 应该是取消选中（同一个 entry.id）
    fireEvent.click(screen.getByText('panel-toggle-memory'))
    await waitFor(() => expect(screen.getByTestId('selected-memories').textContent).toBe(''))

    fireEvent.click(screen.getByText('panel-toggle-memory'))
    await waitFor(() => expect(screen.getByTestId('selected-memories').textContent).toBe('mem-1'))
    fireEvent.click(screen.getByText('panel-remove-memory'))
    await waitFor(() => expect(screen.getByTestId('selected-memories').textContent).toBe(''))

    fireEvent.click(screen.getByText('panel-toggle-memory'))
    await waitFor(() => expect(screen.getByTestId('selected-memories').textContent).toBe('mem-1'))
    fireEvent.click(screen.getByText('panel-clear-memories'))
    await waitFor(() => expect(screen.getByTestId('selected-memories').textContent).toBe(''))
  })

  it('把当前 branchId 传给 SandboxCharacterPanel', async () => {
    localStorage.setItem('story-sandbox-mode:novel-1', 'chapter')
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/api/chapters')) {
        return { ok: true, json: async () => ({ chapters: [{ chapter: 1 }] }) } as Response
      }
      if (String(url).includes('/api/story-sandbox/branches')) {
        return {
          ok: true,
          json: async () => ({ branches: [{ id: 'b1', chapter: 1, name: '主线', created_at: '', updated_at: '' }] }),
        } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    })
    renderWithProviders(<StorySandboxPage />, {
      activeNovelId: 'novel-1',
      preloadedState: { ui: { chapter: 1 } },
    })
    await waitFor(() => expect(screen.getByTestId('cast-panel').getAttribute('data-branch-id')).toBe('b1'))
  })

  it('regression: switching novel-A -> novel-B -> back to novel-A restores A\'s previously-resolved branch instead of leaving it unresolved', async () => {
    localStorage.setItem('story-sandbox-mode:novel-A', 'chapter')
    localStorage.setItem('story-sandbox-mode:novel-B', 'chapter')
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      const u = String(url)
      if (u.includes('/api/chapters')) {
        return { ok: true, json: async () => ({ chapters: [{ chapter: 1 }] }) } as Response
      }
      if (u.includes('/api/story-sandbox/branches')) {
        const branches = u.includes('novel_id=novel-A')
          ? [{ id: 'a1', chapter: 1, name: 'A线', created_at: '', updated_at: '' }]
          : [{ id: 'b1', chapter: 1, name: 'B线', created_at: '', updated_at: '' }]
        return { ok: true, json: async () => ({ branches }) } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    })

    const client = new (await import('@tanstack/react-query')).QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    })
    const setActive = (id: string) => {
      client.setQueryData(['novels'], [
        { id: 'novel-A', name: 'A', active: id === 'novel-A' },
        { id: 'novel-B', name: 'B', active: id === 'novel-B' },
      ])
    }
    setActive('novel-A')
    const { buildTestStore } = await import('@/test/renderWithClient')
    const { Provider } = await import('react-redux')
    const { QueryClientProvider } = await import('@tanstack/react-query')
    const store = buildTestStore({ ui: { chapter: 1 } } as never)
    const Wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </Provider>
    )
    const { rerender } = render(<StorySandboxPage />, { wrapper: Wrapper })

    // Novel A resolves and auto-persists its only branch.
    await waitFor(() => expect(screen.getByTestId('cast-panel').getAttribute('data-branch-id')).toBe('a1'))

    // Switch to novel B.
    setActive('novel-B')
    rerender(<StorySandboxPage />)
    await waitFor(() => expect(screen.getByTestId('cast-panel').getAttribute('data-branch-id')).toBe('b1'))

    // Switch back to novel A -- should restore 'a1', not get stuck unresolved / wrong.
    setActive('novel-A')
    rerender(<StorySandboxPage />)
    await waitFor(() => expect(screen.getByTestId('cast-panel').getAttribute('data-branch-id')).toBe('a1'))
  })
})
