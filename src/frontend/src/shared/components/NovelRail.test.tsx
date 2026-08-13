import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import NovelRail from '@/shared/components/NovelRail'
import { renderWithProviders } from '@/test/renderWithClient'
import Toaster from '@/shared/components/Toaster'
import { useToast } from '@/shared/hooks/useToast'
import type { RootState } from '@/shared/store/store'

// The confirm() toast is normally rendered by a single <Toaster> mounted at the App.tsx level,
// outside this component's own subtree -- mount a local host reading the same useToast()
// singleton alongside NovelRail so confirm/cancel buttons show up in this test's DOM too.
function ToasterHost() {
  const { toasts, dismiss } = useToast()
  return <Toaster toasts={toasts} onDismiss={dismiss} />
}

vi.mock('@/shared/utils/novels', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/utils/novels')>()
  return {
    ...actual,
    fetchNovels: vi.fn(),
    createNovel: vi.fn(),
    copyNovel: vi.fn(),
    renameNovel: vi.fn(),
    deleteNovel: vi.fn(),
    listProseStyles: vi.fn(),
    getProseStyle: vi.fn(),
    setProseStyle: vi.fn(),
    getProseStylePresetContent: vi.fn(),
  }
})
import { fetchNovels, createNovel, copyNovel, renameNovel, deleteNovel, listProseStyles, getProseStyle } from '@/shared/utils/novels'

//This jsdom environment is unavailable localStorage → install a memory stub (the component has been fault-tolerant for missing, here is to verify persistence)
const origLocalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
beforeEach(() => {
  cleanup()
  vi.clearAllMocks()
  const store: Record<string, string> = {}
  const mem = {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => { store[k] = String(v) },
    removeItem: (k: string) => { delete store[k] },
    clear: () => { for (const k of Object.keys(store)) delete store[k] },
  }
  Object.defineProperty(globalThis, 'localStorage', { value: mem, configurable: true, writable: true })
  vi.mocked(fetchNovels).mockResolvedValue([
    { id: 'a', name: '甲小说', active: true },
    { id: 'b', name: '乙小说', active: false },
  ])
  vi.mocked(listProseStyles).mockResolvedValue([{ id: 'plain-direct', title: '语感调色：大白话直白体' }])
  vi.mocked(getProseStyle).mockResolvedValue({ preset: 'plain-direct', custom_addendum: '' })
  // Default service-status stub so tests that don't care about connectivity icons
  // get a safe response instead of hitting real fetch.
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/api/health/service-status') {
      return {
        ok: true,
        json: async () => ({
          llm: { status: 'ok', error: null },
          search: { status: 'disabled', error: null },
        }),
      }
    }
    return { ok: true, json: async () => ({}) }
  }))
})
//Restore the global situation to avoid stub leakage to other test files (an occasional root cause when sharing workers)
afterEach(() => {
  if (origLocalStorage) Object.defineProperty(globalThis, 'localStorage', origLocalStorage)
  else delete (globalThis as { localStorage?: unknown }).localStorage
  vi.unstubAllGlobals()
})

let seenPath = ''
function LocationProbe() {
  seenPath = useLocation().pathname
  return null
}

function renderRail({
  initialPath = '/novel/a/pipeline',
  preloadedState,
}: { initialPath?: string; preloadedState?: Partial<RootState> } = {}) {
  seenPath = ''
  // activeNovelId: '' skips renderWithProviders' own ['novels'] seed (staleTime:Infinity would
  // otherwise starve out the mocked fetchNovels() response below).
  return renderWithProviders(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/novel/:novelId/*" element={<><NovelRail /><LocationProbe /><ToasterHost /></>} />
      </Routes>
    </MemoryRouter>,
    { activeNovelId: '', preloadedState },
  )
}

describe('NovelRail', () => {
  it('展开态：列出小说，点击切换、[+]新建', async () => {
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    expect(screen.getByText('乙小说')).toBeTruthy()
    fireEvent.click(screen.getByText('乙小说'))
    expect(seenPath).toBe('/novel/b/chat')

    vi.mocked(createNovel).mockResolvedValue({ ok: true, id: 'c' })
    fireEvent.click(screen.getByRole('button', { name: '新建小说' }))
    const input = await screen.findByPlaceholderText('请输入小说名称')
    fireEvent.change(input, { target: { value: '新小说' } })
    fireEvent.click(screen.getByRole('button', { name: '创建' }))
    await waitFor(() => expect(createNovel).toHaveBeenCalledWith('新小说', false))
  })

  it('⋯ 菜单-复制（当前激活小说）', async () => {
    const user = userEvent.setup()
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    vi.mocked(copyNovel).mockResolvedValue({ ok: true, id: 'copy' })
    await user.click(screen.getAllByTitle('更多')[0])
    await user.click(await screen.findByRole('menuitem', { name: /复制/ }))
    const input = await screen.findByDisplayValue('甲小说 副本')
    fireEvent.change(input, { target: { value: '甲小说 副本' } })
    fireEvent.click(screen.getByRole('button', { name: '复制' }))
    await waitFor(() => expect(copyNovel).toHaveBeenCalledWith('a', '甲小说 副本'))
  })

  it('⋯ 菜单-重命名（当前激活小说）', async () => {
    const user = userEvent.setup()
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    vi.mocked(renameNovel).mockResolvedValue({ ok: true })
    await user.click(screen.getAllByTitle('更多')[0])
    await user.click(await screen.findByRole('menuitem', { name: /重命名/ }))
    const input = await screen.findByDisplayValue('甲小说')
    fireEvent.change(input, { target: { value: '改名了' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(renameNovel).toHaveBeenCalledWith('a', '改名了'))
  })

  it('⋯ 菜单-删除（当前激活小说）', async () => {
    const user = userEvent.setup()
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    vi.mocked(deleteNovel).mockResolvedValue({ ok: true })
    await user.click(screen.getAllByTitle('更多')[0])
    await user.click(await screen.findByRole('menuitem', { name: /删除/ }))
    await waitFor(() => expect(screen.getByText(/此操作不可撤销/)).toBeTruthy())
    fireEvent.click(screen.getByText('确定'))
    await waitFor(() => expect(deleteNovel).toHaveBeenCalledWith('a'))
  })

  it('⋯ 菜单-删除（非当前小说）：应删除被点击的目标小说，而非当前查看的小说', async () => {
    const user = userEvent.setup()
    renderRail() // initialPath: /novel/a/pipeline -- viewing/active novel is 'a'
    await waitFor(() => expect(screen.getByText('乙小说')).toBeTruthy())
    vi.mocked(deleteNovel).mockResolvedValue({ ok: true })
    await user.click(screen.getAllByTitle('更多')[1])
    await user.click(await screen.findByRole('menuitem', { name: /删除/ }))
    await waitFor(() => expect(screen.getByText(/此操作不可撤销/)).toBeTruthy())
    fireEvent.click(screen.getByText('确定'))
    await waitFor(() => expect(deleteNovel).toHaveBeenCalledWith('b'))
    expect(deleteNovel).not.toHaveBeenCalledWith('a')
  })

  it('单部小说时删除禁用', async () => {
    const user = userEvent.setup()
    vi.mocked(fetchNovels).mockResolvedValue([{ id: 'a', name: '甲小说', active: true }])
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    await user.click(screen.getByTitle('更多'))
    const deleteItem = screen.getByRole('menuitem', { name: /删除/ })
    expect(deleteItem.getAttribute('data-disabled')).not.toBeNull()
  })

  it('authorLoop running 时切换/新建按钮仍可点击', async () => {
    renderRail({ preloadedState: { authorLoop: { status: 'running', chapter: 1, total: 0, messages: [], resumableChapters: [], hydratedChapter: null, hydrateEpoch: 0, liveRun: false, lastAutoSave: null } } })
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    expect((screen.getByRole('button', { name: '乙小说' }) as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByRole('button', { name: '新建小说' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('折叠按钮：切到窄图标栏（首字按钮 + 可展开回来）', async () => {
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '折叠小说栏' }))
    //Show first word button + expand button after folding
    expect(screen.getByRole('button', { name: '展开小说栏' })).toBeTruthy()
    expect(screen.getByText('甲')).toBeTruthy()  //initial word
    fireEvent.click(screen.getByRole('button', { name: '展开小说栏' }))
    expect(screen.getByText('甲小说')).toBeTruthy()  //Return to expand
  })

  it('折叠态持久化到 localStorage', async () => {
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '折叠小说栏' }))
    expect(localStorage.getItem('chronos.novelRail.collapsed')).toBe('1')
  })

  it('折叠态首字按钮点击切换小说', async () => {
    localStorage.setItem('chronos.novelRail.collapsed', '1')
    renderRail()
    await waitFor(() => expect(screen.getByText('乙')).toBeTruthy())  //B's first letter
    fireEvent.click(screen.getByText('乙'))
    expect(seenPath).toBe('/novel/b/chat')
  })

  it('设定菜单：文风子项展示语感调色', async () => {
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    await userEvent.click(screen.getByRole('button', { name: '设定' }))
    await userEvent.click(screen.getByRole('button', { name: /文风/ }))
    expect(await screen.findByText('语感调色')).toBeTruthy()
    await waitFor(() => expect(listProseStyles).toHaveBeenCalled())
  })

  it('搜索框按名称过滤小说列表', async () => {
    const user = userEvent.setup()
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())
    expect(screen.getByText('乙小说')).toBeTruthy()

    const search = screen.getByRole('searchbox', { name: '搜索小说' })
    await user.type(search, '甲')
    expect(screen.getByText('甲小说')).toBeTruthy()
    expect(screen.queryByText('乙小说')).toBeNull()
  })

  it('搜索无匹配时显示空状态', async () => {
    const user = userEvent.setup()
    renderRail()
    await waitFor(() => expect(screen.getByText('甲小说')).toBeTruthy())

    const search = screen.getByRole('searchbox', { name: '搜索小说' })
    await user.type(search, '不存在')
    expect(screen.getByText('未找到匹配「不存在」的小说')).toBeTruthy()
    expect(screen.queryByText('甲小说')).toBeNull()
    expect(screen.queryByText('乙小说')).toBeNull()
  })
})

describe('NovelRail 服务连通性图标', () => {
  it('挂载时拉取后端 service-status，不主动 ping', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url}`)
      if (url === '/api/health/service-status') {
        return {
          ok: true,
          json: async () => ({
            llm: { status: 'ok', error: null },
            search: { status: 'ok', error: null },
          }),
        }
      }
      return { ok: true, json: async () => ({}) }
    }))
    renderRail()
    await waitFor(() => expect(calls).toContain('GET /api/health/service-status'))
    expect(calls.some(c => c.includes('ping-llm'))).toBe(false)
    expect(calls.some(c => c.includes('ping-search'))).toBe(false)
  })

  it('后端返回 disabled 时图标显示已关闭', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/health/service-status') {
        return {
          ok: true,
          json: async () => ({
            llm: { status: 'ok', error: null },
            search: { status: 'disabled', error: null },
          }),
        }
      }
      return { ok: true, json: async () => ({}) }
    }))
    renderRail()
    await waitFor(() => expect(screen.getByTitle(/启动自动检测已关闭/)).toBeTruthy())
  })
})
