import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithClient'
import SandboxCharacterPanel from '@/features/sandbox/components/SandboxCharacterPanel'

vi.mock('@/shared/utils/archives', () => ({
  fetchArchiveOverview: vi.fn(),
  fetchChapterArchives: vi.fn(),
  fetchSandboxCastArchives: vi.fn(),
  fetchSandboxRelatedCastArchives: vi.fn(),
  fetchSandboxMemoryArchive: vi.fn(),
}))
vi.mock('@/shared/utils/setup', () => ({
  fetchCast: vi.fn(),
  fetchRelationshipGraph: vi.fn(),
}))
import { fetchSandboxCastArchives, fetchSandboxRelatedCastArchives, fetchSandboxMemoryArchive } from '@/shared/utils/archives'
import { fetchCast, fetchRelationshipGraph } from '@/shared/utils/setup'

const MOCK_CHARACTER = {
  name: '角色A',
  role: '测试',
  causal_anchors: {},
  sliders: { resistance: { value: 4, label: '抗拒中' } },
  location: 'X',
  gender: 'female' as const,
}

beforeEach(() => {
  cleanup()
  try {
    localStorage.setItem('chronos.sandboxCharacterPanel.collapsed', '0')
    localStorage.setItem('chronos.sandboxCharacterPanel.charactersCollapsed', '0')
    localStorage.setItem('chronos.sandboxCharacterPanel.memoryCollapsed', '0')
  } catch {
    /* test env may lack localStorage */
  }
  vi.mocked(fetchSandboxCastArchives).mockResolvedValue({
    characters: [MOCK_CHARACTER],
  })
  vi.mocked(fetchSandboxRelatedCastArchives).mockResolvedValue({ characters: [] })
  vi.mocked(fetchSandboxMemoryArchive).mockResolvedValue([])
  vi.mocked(fetchCast).mockResolvedValue([])
  vi.mocked(fetchRelationshipGraph).mockResolvedValue({ groups: {}, edges: {} })
})

describe('SandboxCharacterPanel', () => {
  it('默认展示在场角色 tab 与角色卡，支持全部展开/折叠', async () => {
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={2} activeCast={['角色A']} />,
    )
    expect(await screen.findByRole('tab', { name: '在场角色' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: '在场角色' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByText('第2章')).toBeTruthy()
    expect(await screen.findByText('角色A')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '全部展开' }))
    expect(await screen.findByText('抗拒中')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '全部折叠' }))
    await waitFor(() => {
      expect(screen.queryByText('抗拒中')).toBeNull()
    })
  })

  it('chapter 为 0 时副标题显示自由模式', async () => {
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={0} activeCast={['角色A']} />,
    )
    expect(await screen.findByRole('tab', { name: '在场角色' })).toBeTruthy()
    expect(screen.getByText('自由模式')).toBeTruthy()
  })

  it('无在场角色时显示空态', async () => {
    vi.mocked(fetchSandboxCastArchives).mockResolvedValue({ characters: [] })
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={3} activeCast={[]} />,
    )
    expect(await screen.findByText('当前没有在场角色')).toBeTruthy()
  })

  it('切到相关角色 tab 后展示相关角色档案，且无相关角色时显示对应空态', async () => {
    vi.mocked(fetchSandboxRelatedCastArchives).mockResolvedValue({
      characters: [{ ...MOCK_CHARACTER, name: '角色B' }],
    })
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={3} activeCast={['角色A']} />,
    )
    await screen.findByText('角色A')
    fireEvent.click(screen.getByRole('tab', { name: '相关角色' }))
    expect(await screen.findByText('角色B')).toBeTruthy()
    expect(screen.queryByText('角色A')).toBeNull()

    vi.mocked(fetchSandboxRelatedCastArchives).mockResolvedValue({ characters: [] })
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={3} activeCast={[]} />,
    )
    fireEvent.click(screen.getAllByRole('tab', { name: '相关角色' })[1])
    expect(await screen.findByText('当前没有相关角色')).toBeTruthy()
  })

  it('可手动收起/展开整个 panel', async () => {
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={2} activeCast={['角色A']} />,
    )
    expect(await screen.findByRole('tab', { name: '在场角色' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '收起角色面板' }))
    expect(screen.queryByRole('tab', { name: '在场角色' })).toBeNull()
    expect(screen.getByRole('button', { name: '展开角色面板' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '展开角色面板' }))
    expect(await screen.findByRole('tab', { name: '在场角色' })).toBeTruthy()
  })

  it('passes hasPortrait=true to CharacterCard when the cast roster has a portrait_path', async () => {
    vi.mocked(fetchCast).mockResolvedValue([{ name: '角色A', portrait_path: '角色A-123.png' }])
    const { container } = renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={2} activeCast={['角色A']} />,
    )
    await screen.findByText('角色A')
    expect(container.querySelector('img')).not.toBeNull()
  })
})

describe('SandboxCharacterPanel live profile preview', () => {
  it('highlights a field freshly mutated this round, sourced from Redux liveProfileMutations', async () => {
    vi.mocked(fetchSandboxCastArchives).mockResolvedValue({
      characters: [{
        name: '甲', role: '同质堕落型', causal_anchors: {}, sliders: {}, personality: '外冷内热',
      }],
    })
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-a" chapter={1} activeCast={['甲']} />,
      { activeNovelId: 'novel-a', preloadedState: { sandbox: {
        busy: false,
        liveProfileMutations: { 甲: { fields: { personality: '疯狂' }, at: Date.now() } },
      } } },
    )
    expect(await screen.findByText('甲')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /甲/ }))
    expect(await screen.findByText('疯狂')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '性格' }).className).toContain('ring-rose-300')
  })
})

const MOCK_MEMORY = {
  id: 'mem-1', chapter: 3, turnIndex: 1, time: '子夜', location: '藏经阁',
  characters: ['甲'], summary: '甲把玉佩交给了乙', entities: ['玉佩'], branchId: null,
}

describe('SandboxCharacterPanel 归档记忆分组', () => {
  beforeEach(() => {
    vi.mocked(fetchSandboxMemoryArchive).mockResolvedValue([MOCK_MEMORY])
  })

  it('展示归档记忆分组标题与条目', async () => {
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={3} activeCast={['角色A']} />,
    )
    expect(await screen.findByText('归档记忆')).toBeTruthy()
    expect(await screen.findByText('甲把玉佩交给了乙')).toBeTruthy()
  })

  it('归档记忆分组的折叠不影响角色 tab 分组', async () => {
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={3} activeCast={['角色A']} />,
    )
    await screen.findByText('甲把玉佩交给了乙')
    fireEvent.click(screen.getByRole('button', { name: '归档记忆' }))
    await waitFor(() => expect(screen.queryByText('甲把玉佩交给了乙')).toBeNull())
    // 在场角色 tab 仍展开，角色卡还在
    expect(screen.getByText('角色A')).toBeTruthy()
  })

  it('搜索框按子串过滤，清空后恢复全量', async () => {
    vi.mocked(fetchSandboxMemoryArchive).mockResolvedValue([
      MOCK_MEMORY,
      { ...MOCK_MEMORY, id: 'mem-2', summary: '完全不相关的事', characters: [], entities: [], location: '', time: '' },
    ])
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={3} activeCast={['角色A']} />,
    )
    await screen.findByText('甲把玉佩交给了乙')
    const input = screen.getByPlaceholderText('搜索记忆…')
    fireEvent.change(input, { target: { value: '玉佩' } })
    expect(screen.queryByText('完全不相关的事')).toBeNull()
    expect(screen.getByText('甲把玉佩交给了乙')).toBeTruthy()
    fireEvent.change(input, { target: { value: '' } })
    expect(await screen.findByText('完全不相关的事')).toBeTruthy()
  })

  it('无匹配结果时显示提示', async () => {
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={3} activeCast={['角色A']} />,
    )
    await screen.findByText('甲把玉佩交给了乙')
    fireEvent.change(screen.getByPlaceholderText('搜索记忆…'), { target: { value: '不存在的关键词' } })
    expect(await screen.findByText('无匹配结果')).toBeTruthy()
  })

  it('没有归档记忆时显示空态', async () => {
    vi.mocked(fetchSandboxMemoryArchive).mockResolvedValue([])
    renderWithProviders(
      <SandboxCharacterPanel novelId="novel-1" chapter={3} activeCast={['角色A']} />,
    )
    expect(await screen.findByText('暂无归档记忆')).toBeTruthy()
  })

  it('点击一条记忆触发 onToggleMemory', async () => {
    const onToggleMemory = vi.fn()
    renderWithProviders(
      <SandboxCharacterPanel
        novelId="novel-1" chapter={3} activeCast={['角色A']}
        selectedMemoryIds={new Set()} onToggleMemory={onToggleMemory}
      />,
    )
    const item = await screen.findByRole('button', { name: /甲把玉佩交给了乙/ })
    fireEvent.click(item)
    expect(onToggleMemory).toHaveBeenCalledWith(MOCK_MEMORY)
  })

  it('selectedMemoryIds 命中的条目渲染选中态', async () => {
    renderWithProviders(
      <SandboxCharacterPanel
        novelId="novel-1" chapter={3} activeCast={['角色A']}
        selectedMemoryIds={new Set(['mem-1'])} onToggleMemory={vi.fn()}
      />,
    )
    const item = await screen.findByRole('button', { name: /甲把玉佩交给了乙/ })
    expect(item.getAttribute('aria-pressed')).toBe('true')
  })
})
