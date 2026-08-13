import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, cleanup } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithClient'
import CharacterArchivePage from '@/features/archives/components/CharacterArchivePage'

vi.mock('@/shared/utils/archives', () => ({
  fetchArchiveOverview: vi.fn(),
  fetchChapterArchives: vi.fn(),
}))
vi.mock('@/shared/utils/setup', () => ({
  fetchCast: vi.fn(),
  fetchRelationshipGraph: vi.fn(),
}))
import { fetchArchiveOverview, fetchChapterArchives } from '@/shared/utils/archives'
import { fetchCast, fetchRelationshipGraph } from '@/shared/utils/setup'

beforeEach(() => {
  cleanup()
  vi.mocked(fetchArchiveOverview).mockResolvedValue({
    built: [{ chapter: 1, characters: ['角色A'] }, { chapter: 2, characters: ['角色A'] }],
    plot_chapters: [
      { chapter: 1, roster: ['角色A'], built: ['角色A'] },
      { chapter: 2, roster: ['角色A'], built: ['角色A'] },
      { chapter: 3, roster: ['角色A'], built: [] },
    ],
  })
  vi.mocked(fetchChapterArchives).mockResolvedValue({
    chapter: 1,
    characters: [{
      name: '角色A', role: '测试', causal_anchors: {},
      sliders: { resistance: { value: 4, label: '抗拒中' } }, location: 'X', gender: 'female',
      thought_process: { delta: 'd', escalation: 'e' },
    }],
  })
  vi.mocked(fetchCast).mockResolvedValue([])
  vi.mocked(fetchRelationshipGraph).mockResolvedValue({ groups: {}, edges: {} })
})

import type { RootState } from '@/shared/store/store'

function setup(preloadedState?: Partial<RootState>) {
  return renderWithProviders(<CharacterArchivePage />, { preloadedState })
}

async function expandCharacterAndStage() {
  fireEvent.click(await screen.findByRole('button', { name: '全部展开' }))
}

describe('CharacterArchivePage', () => {
  it('渲染章节下拉与该章角色 + 滑块 label', async () => {
    setup()
    const select = await screen.findByRole('combobox', { name: '选择章节' })
    expect(select.textContent).toContain('第1章')
    expect(await screen.findByText('角色A')).toBeTruthy()
    await expandCharacterAndStage()
    expect(await screen.findByText('抗拒中')).toBeTruthy()
  })

  it('全部展开/折叠 toggle 可切换', async () => {
    setup()
    const toggle = await screen.findByRole('button', { name: '全部展开' })
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: '全部折叠' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '全部折叠' }))
    expect(screen.getByRole('button', { name: '全部展开' })).toBeTruthy()
  })

  it('按角色名搜索过滤列表并显示匹配数', async () => {
    vi.mocked(fetchChapterArchives).mockResolvedValue({
      chapter: 1,
      characters: [
        { name: '林晚', role: '测', causal_anchors: {}, sliders: {}, location: 'X', gender: 'female' },
        { name: '角色A', role: '测', causal_anchors: {}, sliders: {}, location: 'X', gender: 'female' },
      ],
    })
    setup()
    expect(await screen.findByText('林晚')).toBeTruthy()
    expect(screen.getByText('角色A')).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText('搜索角色名'), { target: { value: '林' } })
    expect(screen.getByText(/共 2 人 · 匹配 1/)).toBeTruthy()
    expect(screen.getByText('林晚')).toBeTruthy()
    expect(screen.queryByText('角色A')).toBeNull()
  })

  it('搜索无匹配时提示并隐藏全部展开', async () => {
    setup()
    await screen.findByText('角色A')
    fireEvent.change(screen.getByPlaceholderText('搜索角色名'), { target: { value: '不存在' } })
    expect(screen.getByText('未找到匹配角色')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '全部展开' })).toBeNull()
  })

  it('渲染 {level,text} 形态 slider 不崩溃', async () => {
    vi.mocked(fetchChapterArchives).mockResolvedValue({
      chapter: 1,
      characters: [{
        name: '角色A', role: '测试', causal_anchors: {},
        sliders: { 侵蚀度: { value: { level: 1, text: '动摇' }, label: '[object Object]' } },
        location: 'X', gender: 'female',
      }],
    })
    setup()
    await expandCharacterAndStage()
    expect(await screen.findByText('动摇')).toBeTruthy()
    expect(screen.getByRole('heading', { name: /侵蚀度/ })).toBeTruthy()
  })

  it('渲染称呼池形态 address_ref/self_ref 不崩溃（React #31 回归）', async () => {
    vi.mocked(fetchChapterArchives).mockResolvedValue({
      chapter: 1,
      characters: [{
        name: '角色A', role: '测试', causal_anchors: {},
        sliders: {}, location: 'X', gender: 'female',
        address_ref: { 小明: ['小明'] },
        self_ref: { _default: ['我', '本小姐'], 林老师: ['学生'] },
      }],
    })
    setup()
    await expandCharacterAndStage()
    expect(await screen.findByText(/对小明：小明/)).toBeTruthy()
    expect(await screen.findByText(/我、本小姐；对林老师：学生/)).toBeTruthy()
  })

  it('渲染 hobbies 列表', async () => {
    vi.mocked(fetchChapterArchives).mockResolvedValue({
      chapter: 1,
      characters: [{
        name: '角色A', role: '测试', causal_anchors: {},
        sliders: {}, location: 'X', gender: 'female',
        hobbies: ['爱吃甜食', '喜欢刺绣'],
      }],
    })
    setup()
    await expandCharacterAndStage()
    expect(await screen.findByText(/爱吃甜食、喜欢刺绣/)).toBeTruthy()
  })

  it('渲染身份背景', async () => {
    vi.mocked(fetchChapterArchives).mockResolvedValue({
      chapter: 1,
      characters: [{
        name: '甲', role: '角色', causal_anchors: {}, sliders: {},
        identity_background: '没落贵族之女，寄人篱下',
      }],
    })
    setup()
    await expandCharacterAndStage()
    expect(await screen.findByText('没落贵族之女，寄人篱下')).toBeTruthy()
  })

  it('渲染旧形态扁平 self_ref 字符串不崩溃', async () => {
    vi.mocked(fetchChapterArchives).mockResolvedValue({
      chapter: 1,
      characters: [{
        name: '角色A', role: '测试', causal_anchors: {},
        sliders: {}, location: 'X', gender: 'female', self_ref: '我',
      }],
    })
    setup()
    await expandCharacterAndStage()
    const heading = await screen.findByRole('heading', { name: '称呼' })
    expect(heading.parentElement?.textContent).toContain('我')
  })

  it('thought_process 在 markdown 中直接展示', async () => {
    setup()
    await expandCharacterAndStage()
    const section = (await screen.findByRole('heading', { name: '内心活动' })).parentElement
    expect(section?.textContent).toContain('delta')
    expect(section?.textContent).toContain('d')
    expect(section?.textContent).toContain('escalation')
    expect(section?.textContent).toContain('e')
  })

  it('缺口章节显示待构建计数，不显示手动构建按钮', async () => {
    vi.mocked(fetchArchiveOverview).mockResolvedValue({
      built: [{ chapter: 1, characters: ['角色A'] }],
      plot_chapters: [
        { chapter: 1, roster: ['角色A'], built: ['角色A'] },
        { chapter: 2, roster: ['角色A', '角色B'], built: [] },
      ],
    })
    setup()
    await screen.findByRole('combobox', { name: '选择章节' })
    expect(screen.queryByRole('button', { name: /一键构建/ })).toBeNull()
    expect(screen.queryByText(/删除第/)).toBeNull()
  })

  it('后台推演进行中时章节标签显示推演中', async () => {
    vi.mocked(fetchArchiveOverview).mockResolvedValue({
      built: [],
      plot_chapters: [{ chapter: 1, roster: ['角色A', '角色B'], built: [] }],
    })
    setup({
      backgroundJobs: {
        byNovelId: { default: { skeletonReviewActive: false, timelineCascadeActive: true } },
      },
    })
    expect(await screen.findByText(/推演中/)).toBeTruthy()
  })

  it('passes hasPortrait=true to CharacterCard when the cast roster has a portrait_path', async () => {
    vi.mocked(fetchCast).mockResolvedValue([{ name: '角色A', portrait_path: '角色A-123.png' }])
    const { container } = setup()
    await screen.findByText('角色A')
    expect(container.querySelector('img')).not.toBeNull()
  })
})
