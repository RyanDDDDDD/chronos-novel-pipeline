import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { ProseBubble, SuggestionsBubble, TurnSegments, InitialContextCard, SelectedDirectionsCard, SelectedMemoriesCard } from './StorySandboxSegments'
import type { SandboxMemoryEntry } from '@/shared/types'

const mockPlotExtensionSkills = [
  { name: 'example-bridges', description: '合成桥段', kind: 'plot-extension', source: 'builtin' },
  { name: 'example-action-skill', description: '合成动作', kind: 'plot-extension', source: 'builtin' },
  { name: 'world-interview', description: '世界观访谈', kind: '', source: 'builtin' },
]

vi.mock('@/shared/queries/setup', () => ({
  useSetupSkills: () => ({ data: mockPlotExtensionSkills }),
}))

function suggestionsOpenState() {
  return screen.getByText(/🧭 剧情走向选择/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')
}

const REGENERATE_HINT_PLACEHOLDER = '给重新生成一点提示（可选，/ 选拓展 skill）…'

afterEach(() => {
  cleanup()
})

describe('ProseBubble', () => {
  it('renders the instruction and prose text', () => {
    render(<ProseBubble instruction="继续" prose="他抬起头。" />)
    expect(screen.getByText('继续')).toBeTruthy()
    expect(screen.getByText('他抬起头。')).toBeTruthy()
  })

  it('renders markdown in the instruction bubble', () => {
    render(<ProseBubble instruction="- 甲追出去解释" prose="他抬起头。" />)
    expect(screen.getByRole('list')).toBeTruthy()
    expect(screen.getByText('甲追出去解释')).toBeTruthy()
  })

  it('renders markdown in the prose bubble', () => {
    render(<ProseBubble instruction="继续" prose="**他抬起头。**" />)
    const strong = screen.getByText('他抬起头。')
    expect(strong.tagName).toBe('STRONG')
  })

  it('does not render the rewrite control when onRewrite is not provided', () => {
    render(<ProseBubble instruction="继续" prose="他抬起头。" />)
    expect(screen.queryByRole('button', { name: '重写这段' })).toBeNull()
    expect(screen.queryByPlaceholderText('重写时怎么改（可选）…')).toBeNull()
  })

  it('calls onRewrite with the typed feedback and clears the input', () => {
    const onRewrite = vi.fn()
    render(<ProseBubble instruction="继续" prose="他抬起头。" onRewrite={onRewrite} />)
    const input = screen.getByPlaceholderText('重写时怎么改（可选）…') as HTMLInputElement
    fireEvent.change(input, { target: { value: '语气再冷淡一点' } })
    fireEvent.click(screen.getByRole('button', { name: '重写这段' }))
    expect(onRewrite).toHaveBeenCalledWith('语气再冷淡一点')
    expect(input.value).toBe('')
  })

  it('submits rewrite feedback when Enter is pressed in the input', () => {
    const onRewrite = vi.fn()
    render(<ProseBubble instruction="继续" prose="他抬起头。" onRewrite={onRewrite} />)
    const input = screen.getByPlaceholderText('重写时怎么改（可选）…') as HTMLInputElement
    fireEvent.change(input, { target: { value: '语气再冷淡一点' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onRewrite).toHaveBeenCalledWith('语气再冷淡一点')
    expect(input.value).toBe('')
  })

  it('calls onRewrite with an empty string when no feedback was typed', () => {
    const onRewrite = vi.fn()
    render(<ProseBubble instruction="继续" prose="他抬起头。" onRewrite={onRewrite} />)
    fireEvent.click(screen.getByRole('button', { name: '重写这段' }))
    expect(onRewrite).toHaveBeenCalledWith('')
  })

  it('while rewriting, disables the control, shows loading label, and displays rewritingProse instead of prose', () => {
    render(
      <ProseBubble
        instruction="继续" prose="他抬起头。" onRewrite={vi.fn()}
        rewriting rewritingProse="甲缓缓"
      />,
    )
    expect(screen.getByRole('button', { name: '重写中…' })).toBeTruthy()
    expect(screen.getByText('甲缓缓')).toBeTruthy()
    expect(screen.queryByText('他抬起头。')).toBeNull()
    const input = screen.getByPlaceholderText('重写时怎么改（可选）…') as HTMLInputElement
    expect(input.disabled).toBe(true)
  })

  it('shows the style-guard rewrite indicator when styleGuardRewriting is true', () => {
    render(<ProseBubble instruction="继续" prose="他抬起头。" styleGuardRewriting />)
    expect(screen.getByText('检测到 AI 味文本，正在重写…')).toBeTruthy()
  })

  it('shows a loading spinner with the status label while prose is empty and loadingStatus is set', () => {
    render(<ProseBubble instruction="继续" prose="" loadingStatus="思考中…" />)
    expect(screen.getByText('思考中…')).toBeTruthy()
  })

  it('hides the loading spinner once prose has content, even if loadingStatus is still set', () => {
    render(<ProseBubble instruction="继续" prose="他抬起头。" loadingStatus="思考中…" />)
    expect(screen.queryByText('思考中…')).toBeNull()
    expect(screen.getByText('他抬起头。')).toBeTruthy()
  })

  it('right-click with a text selection inside the prose shows the rewrite-selection menu item, and confirming calls back with the fragment/offset/feedback', () => {
    const onRewriteSelection = vi.fn()
    const prose = '他抬起头，看向窗外。'
    render(
      <ProseBubble instruction="继续" prose={prose} onRewriteSelection={onRewriteSelection} />,
    )
    const proseEl = screen.getByTestId('prose-content')
    const textNode = proseEl.querySelector('p')!.firstChild as Text
    const start = prose.indexOf('看向窗外')
    const range = document.createRange()
    range.setStart(textNode, start)
    range.setEnd(textNode, start + 4)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(range)

    fireEvent.contextMenu(proseEl)
    expect(screen.getByText('重写选中片段')).toBeTruthy()

    fireEvent.click(screen.getByText('重写选中片段'))
    const input = screen.getByPlaceholderText('重写时怎么改（可选）…')
    fireEvent.change(input, { target: { value: '语气再冷淡一点' } })
    fireEvent.click(screen.getByText('重写'))

    expect(onRewriteSelection).toHaveBeenCalledWith('看向窗外', start, '语气再冷淡一点')
  })

  it('right-click with no active selection does not show the rewrite-selection menu', () => {
    const onRewriteSelection = vi.fn()
    render(
      <ProseBubble
        instruction="继续" prose="他抬起头。" onRewriteSelection={onRewriteSelection}
      />,
    )
    window.getSelection()?.removeAllRanges()
    fireEvent.contextMenu(screen.getByTestId('prose-content'))
    expect(screen.queryByText('重写选中片段')).toBeNull()
  })

  it('does not show the rewrite-selection menu when onRewriteSelection is not provided', () => {
    const prose = '他抬起头，看向窗外。'
    render(<ProseBubble instruction="继续" prose={prose} />)
    const proseEl = screen.getByTestId('prose-content')
    const textNode = proseEl.querySelector('p')!.firstChild as Text
    const start = prose.indexOf('看向窗外')
    const range = document.createRange()
    range.setStart(textNode, start)
    range.setEnd(textNode, start + 4)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(range)
    fireEvent.contextMenu(proseEl)
    expect(screen.queryByText('重写选中片段')).toBeNull()
  })

  it('shows the selection-rewrite loader at the selected fragment position', () => {
    const prose = '他抬起头，看向窗外。乙笑了。'
    render(
      <ProseBubble
        instruction="继续"
        prose={prose}
        selectionRewriting
        selectionRewriteAnchor={{ originalText: '看向窗外', anchorOffset: 5 }}
      />,
    )
    expect(screen.getByRole('status')).toBeTruthy()
    expect(screen.getByText('正在重写选中片段…')).toBeTruthy()
    const proseEl = screen.getByTestId('prose-content')
    expect(proseEl.textContent).toContain('他抬起头，')
    expect(proseEl.textContent).toContain('乙笑了。')
    expect(proseEl.textContent).not.toContain('看向窗外')
  })

  it('does not close the rewrite-selection popover when the feedback input fires its own scroll event (overflowing single-line text)', () => {
    const onRewriteSelection = vi.fn()
    const prose = '他抬起头，看向窗外。'
    render(
      <ProseBubble instruction="继续" prose={prose} onRewriteSelection={onRewriteSelection} />,
    )
    const proseEl = screen.getByTestId('prose-content')
    const textNode = proseEl.querySelector('p')!.firstChild as Text
    const start = prose.indexOf('看向窗外')
    const range = document.createRange()
    range.setStart(textNode, start)
    range.setEnd(textNode, start + 4)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(range)
    fireEvent.contextMenu(proseEl)
    fireEvent.click(screen.getByText('重写选中片段'))

    const input = screen.getByPlaceholderText('重写时怎么改（可选）…')
    // Browsers fire a native 'scroll' event on a single-line <input> when its text overflows
    // the visible width -- this must not be mistaken for the user scrolling the page.
    fireEvent.scroll(input)

    expect(screen.getByPlaceholderText('重写时怎么改（可选）…')).toBeTruthy()
  })

  it('输入重写反馈命中已知角色名/设定名时，输入框下方显示识别提示行', () => {
    render(
      <ProseBubble
        instruction="继续" prose="他抬起头。" onRewrite={vi.fn()}
        characterNames={['李梅']} settingNames={['元气']}
      />,
    )
    const input = screen.getByPlaceholderText('重写时怎么改（可选）…') as HTMLInputElement
    fireEvent.change(input, { target: { value: '让李梅提一下元气的事' } })
    expect(screen.getByText('识别到角色：李梅')).toBeTruthy()
    expect(screen.getByText('识别到设定：元气')).toBeTruthy()
  })

  it('不传 characterNames/settingNames 时不显示识别提示行（回归：默认值不报错）', () => {
    render(<ProseBubble instruction="继续" prose="他抬起头。" onRewrite={vi.fn()} />)
    const input = screen.getByPlaceholderText('重写时怎么改（可选）…') as HTMLInputElement
    fireEvent.change(input, { target: { value: '随便改改' } })
    expect(screen.queryByText(/识别到角色/)).toBeNull()
    expect(screen.queryByText(/识别到设定/)).toBeNull()
  })
})

describe('SelectedDirectionsCard', () => {
  it('renders nothing when directions is empty', () => {
    const { container } = render(<SelectedDirectionsCard directions={[]} onRemove={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('lists each direction on its own row with a remove button', () => {
    const onRemove = vi.fn()
    render(
      <SelectedDirectionsCard
        directions={['甲追出去解释', '乙干脆离开现场']}
        onRemove={onRemove}
      />,
    )
    expect(screen.getByText('🧭 已选剧情走向')).toBeTruthy()
    expect(screen.getByText('甲追出去解释')).toBeTruthy()
    expect(screen.getByText('乙干脆离开现场')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '移除 甲追出去解释' }))
    expect(onRemove).toHaveBeenCalledWith('甲追出去解释')
  })

  it('prefixes each direction with a markdown list marker and renders markdown', () => {
    render(
      <SelectedDirectionsCard
        directions={['**甲**追出去解释']}
        onRemove={vi.fn()}
      />,
    )
    expect(screen.getByText('甲').closest('strong')).toBeTruthy()
    expect(screen.getByText('追出去解释').closest('li')).toBeTruthy()
    // outer card list + ChatMarkdown list for the "- …" item
    expect(screen.getAllByRole('list').length).toBeGreaterThanOrEqual(2)
  })
})

describe('SuggestionsBubble', () => {
  it('renders nothing when there are no options and no onRegenerate', () => {
    const { container } = render(
      <SuggestionsBubble options={[]} selected={new Set()} onToggle={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when there are no options and locked, even with onRegenerate', () => {
    const { container } = render(
      <SuggestionsBubble
        options={[]} selected={new Set()} onToggle={vi.fn()} onRegenerate={vi.fn()} locked
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders an expanded fold with a retry hint (not nothing) when options is empty but onRegenerate is provided -- covers the LLM suggest call degrading to an empty list', () => {
    const onRegenerate = vi.fn()
    const { container } = render(
      <SuggestionsBubble options={[]} selected={new Set()} onToggle={vi.fn()} onRegenerate={onRegenerate} />,
    )
    expect(container.firstChild).not.toBeNull()
    expect(screen.getByText(/🧭 剧情走向选择/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
    expect(screen.getByText('本轮走向建议生成失败或为空，可在下方重新生成')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '重新生成走向' }))
    expect(onRegenerate).toHaveBeenCalledWith('')
  })

  it('defaults to expanded when unlocked so options are clickable', () => {
    render(
      <SuggestionsBubble options={['甲追出去解释']} selected={new Set()} onToggle={vi.fn()} />,
    )
    expect(screen.getByText(/🧭 剧情走向选择/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
    expect(screen.getByText('甲追出去解释')).toBeTruthy()
  })

  it('renders a selected option with aria-pressed=true, an unselected one with false', () => {
    render(
      <SuggestionsBubble
        options={['甲追出去解释', '乙干脆离开现场']}
        selected={new Set(['甲追出去解释'])} onToggle={vi.fn()}
      />,
    )
    expect(screen.getByText('甲追出去解释').getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText('乙干脆离开现场').getAttribute('aria-pressed')).toBe('false')
  })

  it('clicking an option calls onToggle with that text, does not send anything itself', () => {
    const onToggle = vi.fn()
    render(<SuggestionsBubble options={['甲追出去解释']} selected={new Set()} onToggle={onToggle} />)
    fireEvent.click(screen.getByText('甲追出去解释'))
    expect(onToggle).toHaveBeenCalledWith('甲追出去解释')
  })

  it('locked mode keeps submitted styling, disables pills, and defaults to collapsed', () => {
    render(
      <SuggestionsBubble
        options={['甲追出去解释', '乙干脆离开现场']}
        selected={new Set(['甲追出去解释'])}
        locked
      />,
    )
    expect(screen.getByText(/已提交/)).toBeTruthy()
    expect(suggestionsOpenState()).toBe('closed')
    fireEvent.click(screen.getByText(/🧭 剧情走向选择/))
    expect(screen.getByText('甲追出去解释').getAttribute('aria-pressed')).toBe('true')
    expect((screen.getByText('甲追出去解释') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByText('乙干脆离开现场') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByText('乙干脆离开现场'))
    expect(screen.getByText('乙干脆离开现场').getAttribute('aria-pressed')).toBe('false')
  })

  it('locked mode still allows expanding the fold to review the pills', () => {
    render(
      <SuggestionsBubble
        options={['甲追出去解释', '乙干脆离开现场']}
        selected={new Set(['甲追出去解释'])}
        locked
      />,
    )
    expect(suggestionsOpenState()).toBe('closed')
    fireEvent.click(screen.getByText(/🧭 剧情走向选择/))
    expect(suggestionsOpenState()).toBe('open')
    expect((screen.getByText('甲追出去解释') as HTMLButtonElement).disabled).toBe(true)
  })

  it('forceOpen imperatively forces the fold open/closed', () => {
    const { rerender } = render(
      <SuggestionsBubble options={['甲追出去解释']} selected={new Set()} onToggle={vi.fn()} />,
    )
    expect(suggestionsOpenState()).toBe('open')
    rerender(
      <SuggestionsBubble
        options={['甲追出去解释']} selected={new Set()} onToggle={vi.fn()} forceOpen={false}
      />,
    )
    expect(suggestionsOpenState()).toBe('closed')
    rerender(
      <SuggestionsBubble
        options={['甲追出去解释']} selected={new Set()} onToggle={vi.fn()} forceOpen
      />,
    )
    expect(suggestionsOpenState()).toBe('open')
  })
})

describe('TurnSegments derive loading', () => {
  it('shows loading rows for pending characterStates and suggestions', () => {
    const round = {
      instruction: '继续', prose: '他抬起头。',
      characterStates: {}, suggestions: [], sceneState: {},
    }
    render(
      <TurnSegments
        round={round}
        hiddenCats={new Set()}
        selectedDirections={new Set()}
        onToggleDirection={vi.fn()}
        isLatest={false}
        pendingFields={{ characterStates: true, suggestions: true }}
      />,
    )
    expect(screen.getByText('正在推演角色状态…')).toBeTruthy()
    expect(screen.getByText('正在推演剧情走向…')).toBeTruthy()
    expect(screen.queryByText(/🧭 剧情走向选择/)).toBeNull()
  })

  it('auto-expands when suggestions first arrive on the active round', () => {
    const round = {
      instruction: '继续', prose: '他抬起头。',
      characterStates: {}, suggestions: [], sceneState: {},
    }
    const { rerender } = render(
      <TurnSegments
        round={round}
        hiddenCats={new Set()}
        selectedDirections={new Set()}
        onToggleDirection={vi.fn()}
        isLatest={false}
        pendingFields={{ suggestions: true }}
      />,
    )
    expect(screen.getByText('正在推演剧情走向…')).toBeTruthy()
    rerender(
      <TurnSegments
        round={{ ...round, suggestions: ['新建议A', '新建议B'] }}
        hiddenCats={new Set()}
        selectedDirections={new Set()}
        onToggleDirection={vi.fn()}
        isLatest={false}
        pendingFields={{}}
      />,
    )
    expect(screen.getByText(/🧭 剧情走向选择/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
    expect(screen.getByText('新建议A')).toBeTruthy()
  })
})

describe('TurnSegments', () => {
  const round = {
    instruction: '继续', prose: '他抬起头。',
    characterStates: { 甲: { psychology: '平静', posture: '', clothing: '', action: '', demeanor: '' } },
    suggestions: ['某建议'],
    sceneState: {},
  }

  it('renders prose and unlocked suggestions expanded, state collapsed by default', () => {
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.getByText('他抬起头。')).toBeTruthy()
    expect(screen.getByText(/🧬 角色状态（推演）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
    expect(screen.getByText(/🧭 剧情走向选择/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
  })

  it('forceOpen forces both the state bubble and the suggestions fold open', () => {
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest={false} forceOpen
      />,
    )
    expect(screen.getByText(/🧬 角色状态（推演）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
    expect(screen.getByText(/🧭 剧情走向选择/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
  })

  it('hides a segment category when it is in hiddenCats', () => {
    render(
      <TurnSegments
        round={round} hiddenCats={new Set(['state'])} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/🧬 角色状态（推演）/)).toBeNull()
  })

  it('renders each event-log bubble when round.eventLogEntries is non-empty', () => {
    render(
      <TurnSegments
        round={{
          ...round,
          eventLogEntries: [{ summary: '甲做了事', time: '决战之后' }],
        }}
        hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.getByText(/甲做了事/)).toBeTruthy()
    expect(screen.getByText(/决战之后/)).toBeTruthy()
  })

  it('aggregates multiple event-log entries under a single bubble', () => {
    render(
      <TurnSegments
        round={{
          ...round,
          eventLogEntries: [
            { summary: '甲回忆起童年', time: '闪回' },
            { summary: '乙回忆起师父', time: '闪回' },
          ],
        }}
        hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.getAllByText(/🕮 记忆归档/)).toHaveLength(1)
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.getByText(/甲回忆起童年/)).toBeTruthy()
    expect(screen.getByText(/乙回忆起师父/)).toBeTruthy()
  })

  it('renders nothing extra when round.eventLogEntries is empty', () => {
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/记忆归档/)).toBeNull()
  })

  it('hides the event-log bubble when the state category is hidden', () => {
    render(
      <TurnSegments
        round={{
          ...round,
          eventLogEntries: [{ summary: '甲做了事', time: '决战之后' }],
        }}
        hiddenCats={new Set(['state'])} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/甲做了事/)).toBeNull()
  })

  it('renders the rolling-summary bubble when round.rollingSummaryAfter is set', () => {
    render(
      <TurnSegments
        round={{ ...round, rollingSummaryAfter: '目前为止的剧情摘要' }}
        hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    fireEvent.click(screen.getByText(/📜 剧情摘要（滚动）/))
    expect(screen.getByText(/目前为止的剧情摘要/)).toBeTruthy()
  })

  it('renders nothing when round.rollingSummaryAfter is empty', () => {
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/剧情摘要/)).toBeNull()
  })

  it('hides the rolling-summary bubble when the state category is hidden', () => {
    render(
      <TurnSegments
        round={{ ...round, rollingSummaryAfter: '目前为止的剧情摘要' }}
        hiddenCats={new Set(['state'])} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/目前为止的剧情摘要/)).toBeNull()
  })

  it('renders recall content when round.recallContext is set', () => {
    render(
      <TurnSegments
        round={{ ...round, recallContext: '## 相关历史/设定回收\n- 甲做了事' }}
        hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    fireEvent.click(screen.getByText(/🔍 记忆召回/))
    expect(screen.getByText(/甲做了事/)).toBeTruthy()
  })

  it('renders markdown in the recall-context bubble', () => {
    render(
      <TurnSegments
        round={{ ...round, recallContext: '## 相关历史/设定回收\n- 甲做了事' }}
        hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    fireEvent.click(screen.getByText(/🔍 记忆召回/))
    expect(screen.getByRole('heading', { level: 2, name: '相关历史/设定回收' })).toBeTruthy()
    expect(screen.getByRole('list')).toBeTruthy()
    expect(screen.getByText('甲做了事')).toBeTruthy()
  })

  it('renders a placeholder when round.recallContext is empty', () => {
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    fireEvent.click(screen.getByText(/🔍 记忆召回/))
    expect(screen.getByText(/无相关召回/)).toBeTruthy()
  })

  it('round.recalledSettings 非空时渲染设定回收折叠块，堆叠在记忆召回上方', () => {
    const { container } = render(
      <TurnSegments
        round={{
          ...round,
          recalledSettings: [{ category: 'power_system', name: '元气', desc: '气血流动力量' }],
        }}
        hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.getByText('📚 设定回收 (1)')).toBeTruthy()
    const triggers = Array.from(container.querySelectorAll('[data-slot="collapsible-trigger"]')).map((el) => el.textContent ?? '')
    const settingsIdx = triggers.findIndex((t) => t.includes('设定回收'))
    const recallIdx = triggers.findIndex((t) => t.includes('记忆召回'))
    expect(settingsIdx).toBeGreaterThanOrEqual(0)
    expect(recallIdx).toBeGreaterThan(settingsIdx)
  })

  it('round.recalledSettings 为空时不渲染设定回收折叠块', () => {
    render(
      <TurnSegments
        round={round}
        hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/设定回收/)).toBeNull()
  })

  it('hiddenCats 隐藏 state 分类时设定回收折叠块也一并隐藏', () => {
    render(
      <TurnSegments
        round={{
          ...round,
          recalledSettings: [{ category: 'power_system', name: '元气', desc: '气血流动力量' }],
        }}
        hiddenCats={new Set(['state'])} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/设定回收/)).toBeNull()
  })

  it('hides the recall-context bubble when the state category is hidden', () => {
    render(
      <TurnSegments
        round={{ ...round, recallContext: '召回内容' }}
        hiddenCats={new Set(['state'])} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/召回内容/)).toBeNull()
    expect(screen.queryByText(/无相关召回/)).toBeNull()
  })

  it('renders the recall-context bubble before the character-state bubble', () => {
    const { container } = render(
      <TurnSegments
        round={{ ...round, recallContext: '召回内容' }}
        hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    const triggers = Array.from(container.querySelectorAll('[data-slot="collapsible-trigger"]')).map((el) => el.textContent ?? '')
    const recallIdx = triggers.findIndex((t) => t.includes('记忆召回'))
    const characterIdx = triggers.findIndex((t) => t.includes('角色状态'))
    expect(recallIdx).toBeGreaterThanOrEqual(0)
    expect(characterIdx).toBeGreaterThan(recallIdx)
  })
})

describe('SuggestionsBubble regenerate', () => {
  it('does not render the regenerate button when onRegenerate is not provided', () => {
    render(<SuggestionsBubble options={['某建议']} selected={new Set()} onToggle={vi.fn()} />)
    expect(screen.queryByRole('button', { name: '重新生成走向' })).toBeNull()
  })

  it('expands the fold when regenerate is triggered while collapsed', () => {
    const onRegenerate = vi.fn()
    render(<SuggestionsBubble options={['某建议']} selected={new Set()} onToggle={vi.fn()} onRegenerate={onRegenerate} />)
    expect(suggestionsOpenState()).toBe('open')
    fireEvent.click(screen.getByText(/🧭 剧情走向选择/))
    expect(suggestionsOpenState()).toBe('closed')
    fireEvent.click(screen.getByRole('button', { name: '重新生成走向' }))
    expect(suggestionsOpenState()).toBe('open')
  })

  it('calls onRegenerate with the typed hint text', () => {
    const onRegenerate = vi.fn()
    render(<SuggestionsBubble options={['某建议']} selected={new Set()} onToggle={vi.fn()} onRegenerate={onRegenerate} />)
    fireEvent.change(screen.getByPlaceholderText(REGENERATE_HINT_PLACEHOLDER), {
      target: { value: '往乙这边的反应上靠一点' },
    })
    fireEvent.click(screen.getByRole('button', { name: '重新生成走向' }))
    expect(onRegenerate).toHaveBeenCalledWith('往乙这边的反应上靠一点')
  })

  it('submits regenerate hint when Enter is pressed in the input', () => {
    const onRegenerate = vi.fn()
    render(<SuggestionsBubble options={['某建议']} selected={new Set()} onToggle={vi.fn()} onRegenerate={onRegenerate} />)
    const input = screen.getByPlaceholderText(REGENERATE_HINT_PLACEHOLDER) as HTMLInputElement
    fireEvent.change(input, { target: { value: '往乙这边的反应上靠一点' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onRegenerate).toHaveBeenCalledWith('往乙这边的反应上靠一点')
  })

  it('calls onRegenerate with an empty string when no hint was typed', () => {
    const onRegenerate = vi.fn()
    render(<SuggestionsBubble options={['某建议']} selected={new Set()} onToggle={vi.fn()} onRegenerate={onRegenerate} />)
    fireEvent.click(screen.getByRole('button', { name: '重新生成走向' }))
    expect(onRegenerate).toHaveBeenCalledWith('')
  })

  it('does not render the hint input when onRegenerate is not provided', () => {
    render(<SuggestionsBubble options={['某建议']} selected={new Set()} onToggle={vi.fn()} />)
    expect(screen.queryByPlaceholderText(REGENERATE_HINT_PLACEHOLDER)).toBeNull()
  })

  it('shows plot-extension slash menu when hint starts with /', () => {
    render(<SuggestionsBubble options={['某建议']} selected={new Set()} onToggle={vi.fn()} onRegenerate={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText(REGENERATE_HINT_PLACEHOLDER), { target: { value: '/' } })
    expect(screen.getByText('/example-bridges')).toBeTruthy()
    expect(screen.getByText('/example-action-skill')).toBeTruthy()
    expect(screen.queryByText('/world-interview')).toBeNull()
  })

  it('filters slash menu by typed prefix', () => {
    render(<SuggestionsBubble options={['某建议']} selected={new Set()} onToggle={vi.fn()} onRegenerate={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText(REGENERATE_HINT_PLACEHOLDER), { target: { value: '/example-a' } })
    expect(screen.getByText('/example-action-skill')).toBeTruthy()
    expect(screen.queryByText('/example-bridges')).toBeNull()
  })

  it('fills hint with selected slash skill on click', () => {
    render(<SuggestionsBubble options={['某建议']} selected={new Set()} onToggle={vi.fn()} onRegenerate={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText(REGENERATE_HINT_PLACEHOLDER), { target: { value: '/' } })
    fireEvent.click(screen.getByText('/example-bridges'))
    expect((screen.getByPlaceholderText(REGENERATE_HINT_PLACEHOLDER) as HTMLInputElement).value).toBe('/example-bridges ')
  })
})

describe('InitialContextCard', () => {
  it('renders the initial-state card when states are present', () => {
    render(
      <InitialContextCard
        states={{ 甲: { psychology: '外冷内热' } }}
        hiddenCats={new Set()}
      />,
    )
    expect(screen.getByText(/🧬 角色进入态（初始）/)).toBeTruthy()
  })

  it('renders a loading row while pending', () => {
    render(<InitialContextCard pending hiddenCats={new Set()} />)
    expect(screen.getByText('正在推导角色进入态…')).toBeTruthy()
  })

  it('renders nothing when states are absent and not pending', () => {
    const { container } = render(<InitialContextCard hiddenCats={new Set()} />)
    expect(container.firstChild).toBeNull()
  })

  it('forceOpen={false} folds the entry card even though it defaults open', () => {
    render(
      <InitialContextCard
        states={{ 甲: { psychology: '外冷内热' } }}
        scene={{ description: '书房' }}
        hiddenCats={new Set()}
        forceOpen={false}
      />,
    )
    expect(screen.getByText(/🧬 角色进入态（初始）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
    expect(screen.getByText(/🏛️ 场景进入态（初始）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
  })
})

describe('TurnSegments initial state', () => {
  it('does not render initial state inside the turn card', () => {
    const round = {
      instruction: '继续', prose: '他抬起头。',
      characterStates: {}, suggestions: [], sceneState: {},
      initialStates: { 甲: { psychology: '外冷内热' } },
    }
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/🧬 角色进入态（初始）/)).toBeNull()
    expect(screen.getByText('他抬起头。')).toBeTruthy()
  })

  it('renders nothing for initial state when round.initialStates is absent', () => {
    const round = {
      instruction: '继续', prose: '他抬起头。', characterStates: {}, suggestions: [], sceneState: {},
    }
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.queryByText(/🧬 角色进入态（初始）/)).toBeNull()
  })
  it('renders when characterStates is missing on the round object', () => {
    render(
      <TurnSegments
        round={{
          instruction: '继续', prose: '他抬起头。',
          characterStates: undefined as unknown as Record<string, never>,
          suggestions: ['某建议'],
        }}
        hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()} isLatest={false}
      />,
    )
    expect(screen.getByText('他抬起头。')).toBeTruthy()
  })
})

describe('TurnSegments regenerate wiring', () => {
  const round = {
    instruction: '继续', prose: '他抬起头。',
    characterStates: {}, suggestions: ['某建议'],
  }

  it('does not pass onRegenerate through when isLatest is false', () => {
    const onRegenerate = vi.fn()
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest={false} onRegenerate={onRegenerate}
      />,
    )
    expect(screen.queryByRole('button', { name: '重新生成走向' })).toBeNull()
  })

  it('passes onRegenerate through when isLatest is true', () => {
    const onRegenerate = vi.fn()
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest onRegenerate={onRegenerate}
      />,
    )
    expect(screen.getByRole('button', { name: '重新生成走向' })).toBeTruthy()
  })

  it('still renders the suggestions segment (with a retry control) on the latest unlocked round when suggestions came back empty -- regression: the segment used to vanish entirely, taking the only regenerate control with it', () => {
    const onRegenerate = vi.fn()
    const round = { instruction: '继续', prose: '他抬起头。', characterStates: {}, suggestions: [] as string[] }
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest onRegenerate={onRegenerate}
      />,
    )
    expect(screen.getByText(/🧭 剧情走向选择/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '重新生成走向' })).toBeTruthy()
  })

  it('does not render the suggestions segment when suggestions is empty and the round is locked', () => {
    const round = {
      instruction: '继续', prose: '他抬起头。', characterStates: {},
      suggestions: [] as string[], suggestionsLocked: true,
    }
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest onRegenerate={vi.fn()}
      />,
    )
    expect(screen.queryByText(/🧭 剧情走向选择/)).toBeNull()
  })

  it('does not render the suggestions segment when suggestions is empty and the round is not the latest', () => {
    const round = { instruction: '继续', prose: '他抬起头。', characterStates: {}, suggestions: [] as string[] }
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()} selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest={false} onRegenerate={vi.fn()}
      />,
    )
    expect(screen.queryByText(/🧭 剧情走向选择/)).toBeNull()
  })
})

describe('TurnSegments rewrite wiring', () => {
  const round = {
    instruction: '继续', prose: '他抬起头。', characterStates: {}, suggestions: [], sceneState: {},
  }

  it('does not pass onRewrite through when isLatest is false', () => {
    const onRewrite = vi.fn()
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()}
        selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest={false} onRewrite={onRewrite}
      />,
    )
    expect(screen.queryByRole('button', { name: '重写这段' })).toBeNull()
  })

  it('passes onRewrite through when isLatest is true', () => {
    const onRewrite = vi.fn()
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()}
        selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest onRewrite={onRewrite}
      />,
    )
    expect(screen.getByRole('button', { name: '重写这段' })).toBeTruthy()
  })

  it('forwards characterNames/settingNames to ProseBubble rewrite recognition preview', () => {
    render(
      <TurnSegments
        round={round} hiddenCats={new Set()}
        selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest onRewrite={vi.fn()}
        characterNames={['李梅']} settingNames={['元气']}
      />,
    )
    const input = screen.getByPlaceholderText('重写时怎么改（可选）…') as HTMLInputElement
    fireEvent.change(input, { target: { value: '让李梅提一下元气的事' } })
    expect(screen.getByText('识别到角色：李梅')).toBeTruthy()
    expect(screen.getByText('识别到设定：元气')).toBeTruthy()
  })
})

describe('TurnSegments rewrite-selection wiring', () => {
  const round = {
    instruction: '继续', prose: '他抬起头。', characterStates: {}, suggestions: [], sceneState: {},
  }

  it('passes onRewriteSelection through even when isLatest is false -- unlike onRewrite/onRegenerate, the selection-rewrite menu works on any already-completed round regardless of what is currently streaming', () => {
    const onRewriteSelection = vi.fn()
    const prose = '他抬起头，看向窗外。'
    render(
      <TurnSegments
        round={{ ...round, prose }} hiddenCats={new Set()}
        selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest={false} onRewriteSelection={onRewriteSelection}
      />,
    )
    const proseEl = screen.getByTestId('prose-content')
    const textNode = proseEl.querySelector('p')!.firstChild as Text
    const start = prose.indexOf('看向窗外')
    const range = document.createRange()
    range.setStart(textNode, start)
    range.setEnd(textNode, start + 4)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(range)
    fireEvent.contextMenu(proseEl)
    expect(screen.getByText('重写选中片段')).toBeTruthy()
  })

  it('passes onRewriteSelection through when isLatest is true', () => {
    const onRewriteSelection = vi.fn()
    const prose = '他抬起头，看向窗外。'
    render(
      <TurnSegments
        round={{ ...round, prose }} hiddenCats={new Set()}
        selectedDirections={new Set()} onToggleDirection={vi.fn()}
        isLatest onRewriteSelection={onRewriteSelection}
      />,
    )
    const proseEl = screen.getByTestId('prose-content')
    const textNode = proseEl.querySelector('p')!.firstChild as Text
    const start = prose.indexOf('看向窗外')
    const range = document.createRange()
    range.setStart(textNode, start)
    range.setEnd(textNode, start + 4)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(range)
    fireEvent.contextMenu(proseEl)
    expect(screen.getByText('重写选中片段')).toBeTruthy()
  })
})

const MEMORY: SandboxMemoryEntry = {
  id: 'mem-1', chapter: 3, turnIndex: 1, time: '子夜', location: '藏经阁',
  characters: ['甲'], summary: '甲把玉佩交给了乙', entities: [], branchId: null,
}

describe('SelectedMemoriesCard', () => {
  it('无选中记忆时不渲染', () => {
    const { container } = render(<SelectedMemoriesCard memories={[]} onRemove={vi.fn()} />)
    expect(container.textContent).toBe('')
  })

  it('渲染每条记忆的 meta + summary，支持移除', () => {
    const onRemove = vi.fn()
    render(<SelectedMemoriesCard memories={[MEMORY]} onRemove={onRemove} />)
    expect(screen.getByText('🧠 已召回记忆')).toBeTruthy()
    expect(screen.getByText(/甲把玉佩交给了乙/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '移除记忆 mem-1' }))
    expect(onRemove).toHaveBeenCalledWith('mem-1')
  })
})
