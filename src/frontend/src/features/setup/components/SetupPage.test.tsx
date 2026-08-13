import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithClient'
import SetupPage from '@/features/setup/components/SetupPage'
import type { SetupTab } from '@/shared/utils/novelRoute'

vi.mock('@/shared/utils/setup', () => ({
  fetchWorld: vi.fn(),
  fetchCast: vi.fn(),
  fetchPlot: vi.fn(),
  fetchRelationshipGraph: vi.fn(),
  fetchCustomFields: vi.fn().mockResolvedValue([]),
  patchCastCharacter: vi.fn(),
  deleteCastCharacter: vi.fn(),
}))
vi.mock('@/shared/utils/archives', () => ({
  fetchArchiveOverview: vi.fn().mockResolvedValue({ built: [], plot_chapters: [] }),
  fetchChapterArchives: vi.fn().mockResolvedValue({ chapter: 1, characters: [] }),
}))
vi.mock('@/features/setup/utils/skeleton', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/setup/utils/skeleton')>()
  return {
    ...actual,
    fetchChapterSkeleton: vi.fn(),
    patchSkeletonStage: vi.fn().mockResolvedValue({ ok: true }),
  }
})
import { fetchWorld, fetchCast, fetchPlot, fetchRelationshipGraph } from '@/shared/utils/setup'
import { fetchArchiveOverview } from '@/shared/utils/archives'
import { fetchChapterSkeleton, patchSkeletonStage } from '@/features/setup/utils/skeleton'

beforeEach(() => {
  cleanup()
  vi.mocked(fetchWorld).mockResolvedValue({
    world_bible: { factions: [{ name: '甲帮', desc: 'x' }], core_themes: [{ name: 'T', desc: 'td' }] },
  })
  vi.mocked(fetchCast).mockResolvedValue([{ name: '角色甲', role: 'submissive', gender: 'female', identity: '身份句' }])
  vi.mocked(fetchPlot).mockResolvedValue([{ chapter: 1, title: '章一', stages: [{ stage_num: 1, title: 's', location: 'L' }] }])
  vi.mocked(fetchRelationshipGraph).mockResolvedValue({ groups: {}, edges: {} })
  vi.mocked(fetchArchiveOverview).mockResolvedValue({
    built: [],
    plot_chapters: [{ chapter: 1, title: '章一', roster: ['甲'], built: [] }],
  })
  vi.mocked(fetchChapterSkeleton).mockResolvedValue({
    chapter: 1,
    title: '章一',
    stages: [{ stage_num: 1, title: '', location: '', description: '粗纲', expanded: false, beats: [] }],
  })
})

function renderPage(tab: SetupTab = 'world') {
  renderWithProviders(<SetupPage tab={tab} />)
}

async function openCastModal(name: string) {
  fireEvent.click(screen.getByRole('button', { name: `查看${name}详情` }))
  await screen.findByRole('dialog')
}

async function ensureCastEditorOpen() {
  if (!screen.queryByRole('textbox', { name: /编辑.+档案/ })) {
    fireEvent.click(await screen.findByRole('button', { name: '编辑' }))
  }
  return screen.findByRole('textbox', { name: /编辑.+档案/ }) as Promise<HTMLTextAreaElement>
}

async function expectCastEditorMatching(matcher: RegExp) {
  const editor = await ensureCastEditorOpen()
  expect(editor.value).toMatch(matcher)
}

async function expandPlotStage(stageNum: number) {
  const label = await screen.findByText(new RegExp(`Stage ${stageNum}\\b`))
  fireEvent.click(label.closest('[data-slot="accordion-trigger"]') as HTMLElement)
}

describe('SetupPage', () => {
  it('world tab 基调/背景各自独立卡片并带区块标题', async () => {
    vi.mocked(fetchWorld).mockResolvedValue({
      world_bible: {
        tone: '暗黑压抑',
        power_system: [{ name: '灵力分级', desc: '按丹田容量分九阶' }],
        background: '末法时代',
      },
    })
    renderPage('world')
    expect(await screen.findByDisplayValue('暗黑压抑')).toBeTruthy()
    expect(await screen.findByDisplayValue('末法时代')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '基调' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '背景' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '力量体系' })).toBeTruthy()
    expect(await screen.findByDisplayValue('灵力分级')).toBeTruthy()
    expect(await screen.findByDisplayValue('按丹田容量分九阶')).toBeTruthy()
  })

  it('回归：power_system 仍是未迁移的旧格式（自由文本字符串）时不崩溃，直接跳过该区块', async () => {
    vi.mocked(fetchWorld).mockResolvedValue({
      world_bible: {
        tone: '暗黑压抑',
        power_system: '远古秘术锻体所得的「玄脉」，需长期修炼方能激活',
        background: '末法时代',
      },
    })
    renderPage('world')
    expect(await screen.findByDisplayValue('暗黑压抑')).toBeTruthy()
    expect(await screen.findByDisplayValue('末法时代')).toBeTruthy()
    expect(screen.queryByText('力量体系')).toBeNull()
  })

  it('cast tab 渲染 sliders 的 levels 三档梯子', async () => {
    vi.mocked(fetchCast).mockResolvedValue([{
      name: '角色甲', role: 'submissive', gender: 'female', identity: '身份句',
      sliders: {
        投入: {
          level: 1,
          text: '初见时略带戒备',
          levels: { '0': '戒备', '1': '动摇', '2': '沦陷' },
        },
      },
    }])
    renderPage('cast')
    expect(await screen.findByText('角色甲')).toBeTruthy()
    await openCastModal('角色甲')
    await expectCastEditorMatching(/Lv\.0：戒备/)
    await expectCastEditorMatching(/Lv\.1：动摇/)
    await expectCastEditorMatching(/（当前）/)
    await expectCastEditorMatching(/Lv\.2：沦陷/)
  })

  it('cast tab 渲染角色', async () => {
    renderPage('cast')
    expect(await screen.findByText('角色甲')).toBeTruthy()
    await openCastModal('角色甲')
    await expectCastEditorMatching(/身份句/)
  })

  it('cast tab 支持按名搜索', async () => {
    vi.mocked(fetchCast).mockResolvedValue([
      { name: '林晚', role: 'lead', gender: 'female', identity: '晚身份' },
      { name: '角色甲', role: 'submissive', gender: 'female', identity: '甲身份' },
    ])
    renderPage('cast')
    expect(await screen.findByText('林晚')).toBeTruthy()
    expect(screen.getByText('角色甲')).toBeTruthy()

    fireEvent.change(screen.getByPlaceholderText('搜索角色名'), { target: { value: '林' } })
    expect(screen.getByText(/共 2 人 · 匹配 1/)).toBeTruthy()
    expect(screen.getByText('林晚')).toBeTruthy()
    expect(screen.queryByText('角色甲')).toBeNull()
  })

  it('cast tab 搜索无匹配时提示', async () => {
    renderPage('cast')
    await screen.findByText('角色甲')
    fireEvent.change(screen.getByPlaceholderText('搜索角色名'), { target: { value: '没有这个人' } })
    expect(screen.getByText('未找到匹配角色')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /全部展开/ })).toBeNull()
  })

  it('cast tab 渲染 sliders 新形态 {level,text} 不崩溃', async () => {
    vi.mocked(fetchCast).mockResolvedValue([{
      name: '角色甲', role: 'submissive', gender: 'female', identity: '身份句',
      sliders: { 沦陷度: { level: 1, text: '初见时略带戒备' } },
    }])
    renderPage('cast')
    expect(await screen.findByText('角色甲')).toBeTruthy()
    await openCastModal('角色甲')
    await expectCastEditorMatching(/初见时略带戒备/)
  })

  it('plot tab 渲染章节与 stage', async () => {
    renderPage('plot')
    expect(await screen.findByText('第1章')).toBeTruthy()
    expect(await screen.findByDisplayValue('章一')).toBeTruthy()
    expect(await screen.findByText('Stage 1')).toBeTruthy()
  })

  it('plot tab 展示章节摘要：字数与本章角色识别', async () => {
    vi.mocked(fetchCast).mockResolvedValue([
      { name: '甲', role: 'submissive', gender: 'female', identity: '身份句' },
      { name: '乙', role: 'submissive', gender: 'female', identity: '身份句' },
    ])
    vi.mocked(fetchChapterSkeleton).mockResolvedValue({
      chapter: 1,
      exists: true,
      stages: [
        {
          stage_num: 1,
          title: '',
          location: '',
          description: '甲乙 对峙',
          expanded: true,
          beats: [{ text: '拍一' }, { text: '拍 二' }],
        },
        {
          stage_num: 2,
          title: '',
          location: '',
          description: '丙登场',
          expanded: false,
          beats: [],
        },
      ],
    })
    renderPage('plot')
    expect(await screen.findByText('本章字数')).toBeTruthy()
    expect(await screen.findByText(/粗大纲 7 字/)).toBeTruthy()
    expect(await screen.findByText(/分拍底稿 4 字/)).toBeTruthy()
    expect(await screen.findByText('本章角色')).toBeTruthy()
    expect(await screen.findByText('甲、乙')).toBeTruthy()
    expect(await screen.findByText(/粗大纲 4 · 底稿 4/)).toBeTruthy()
    expect(await screen.findByText(/粗大纲 3 · 底稿 0/)).toBeTruthy()
  })

  it('plot tab 分拍底稿下展示台词草稿区块，可编辑', async () => {
    vi.mocked(fetchChapterSkeleton).mockResolvedValue({
      chapter: 1,
      exists: true,
      stages: [{
        stage_num: 1, title: '', location: '', description: '甲乙对峙', expanded: true,
        beats: [{ text: '拍一', sensation_notes: [], dialogue_draft: '甲（意图：试探）：你在做什么。' }],
      }],
    })
    renderPage('plot')
    await expandPlotStage(1)
    expect(await screen.findByText('台词草稿')).toBeTruthy()
    expect(await screen.findByDisplayValue('甲（意图：试探）：你在做什么。')).toBeTruthy()
  })

  it('plot tab 台词草稿为空时显示占位提示', async () => {
    vi.mocked(fetchChapterSkeleton).mockResolvedValue({
      chapter: 1,
      exists: true,
      stages: [{
        stage_num: 1, title: '', location: '', description: '甲乙对峙', expanded: true,
        beats: [{ text: '拍一', sensation_notes: [], dialogue_draft: '' }],
      }],
    })
    renderPage('plot')
    await expandPlotStage(1)
    expect(await screen.findByText('（这拍判断不需要设计台词）')).toBeTruthy()
  })

  it('plot tab 编辑拍正文时保留 sensation_notes/dialogue_draft，不静默清空', async () => {
    vi.mocked(fetchChapterSkeleton).mockResolvedValue({
      chapter: 1,
      exists: true,
      stages: [{
        stage_num: 1, title: '', location: '', description: '甲乙对峙', expanded: true,
        beats: [{ text: '拍一', sensation_notes: ['小腹发烫'], dialogue_draft: '甲：你好。' }],
      }],
    })
    renderPage('plot')
    await expandPlotStage(1)
    const textarea = (await screen.findAllByDisplayValue('拍一'))[0]
    fireEvent.change(textarea, { target: { value: '拍一改' } })
    fireEvent.blur(textarea)
    await waitFor(() => expect(patchSkeletonStage).toHaveBeenCalledWith(1, {
      op: 'replace_beat', stage_num: 1, beat_idx: 0,
      beat: { text: '拍一改', sensation_notes: ['小腹发烫'], dialogue_draft: '甲：你好。' },
    }))
  })

  it('cast tab 通用兜底展示 identity_background/hobbies/verbal_tic/race', async () => {
    vi.mocked(fetchCast).mockResolvedValue([{
      name: '角色甲', role: 'submissive', gender: 'female',
      race: '人类',
      identity_background: '没落贵族之女，寄人篱下',
      hobbies: ['爱吃甜食', '喜欢刺绣'],
      verbal_tic: '句尾爱加「呢」',
    }])
    renderPage('cast')
    expect(await screen.findByText('角色甲')).toBeTruthy()
    await openCastModal('角色甲')
    await expectCastEditorMatching(/没落贵族之女，寄人篱下/)
    await expectCastEditorMatching(/爱吃甜食、喜欢刺绣/)
    await expectCastEditorMatching(/句尾爱加「呢」/)
    await expectCastEditorMatching(/\*\*种族\*\*：人类/)
  })

  it('cast tab 展示 personality 人格字段', async () => {
    vi.mocked(fetchCast).mockResolvedValue([{
      name: '角色甲', role: 'submissive', gender: 'female',
      personality: '表面嘴硬冷漠，内心其实很依恋对方',
    }])
    renderPage('cast')
    expect(await screen.findByText('角色甲')).toBeTruthy()
    await openCastModal('角色甲')
    await expectCastEditorMatching(/表面嘴硬冷漠，内心其实很依恋对方/)
  })

  it('cast tab 通用兜底不重复渲染已定制字段', async () => {
    vi.mocked(fetchCast).mockResolvedValue([{
      name: '角色甲', role: 'submissive', gender: 'female',
      causal_anchors: { 执念: '复仇' },
    }])
    renderPage('cast')
    expect(await screen.findByText('角色甲')).toBeTruthy()
    await openCastModal('角色甲')
    await expectCastEditorMatching(/执念.*复仇/)
  })

  it('tab=archives 时渲染角色档案面板', async () => {
    renderPage('archives')
    expect(await screen.findByLabelText('选择章节')).toBeTruthy()
  })
})
