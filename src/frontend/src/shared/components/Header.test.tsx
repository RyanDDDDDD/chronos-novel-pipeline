import React from 'react'
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import Header from '@/shared/components/Header'
import { renderWithProviders } from '@/test/renderWithClient'
import { EMPTY_VIEW_UNREAD, type ViewUnreadState } from '@/shared/utils/viewUnreadBadges'
import { VIEW_LABELS, SETUP_TAB_LABELS, WORKFLOW_TAB_LABELS } from '@/shared/utils/novelRoute'

beforeEach(() => {
  cleanup()
})
afterEach(() => {
  cleanup()
})

function renderHeader(path: string, viewUnread: ViewUnreadState = EMPTY_VIEW_UNREAD) {
  return renderWithProviders(
    <MemoryRouter initialEntries={[path]}>
      <Header viewUnread={viewUnread} />
    </MemoryRouter>,
    { activeNovelId: '' },
  )
}

describe('Header navigation', () => {
  it('顶栏不含成稿标签，角色档案不作为顶层标签出现（收进设定子菜单）', () => {
    renderHeader('/novel/n1/author')
    expect(screen.queryByRole('button', { name: VIEW_LABELS.manuscript })).toBeNull()
    expect(screen.queryByRole('button', { name: SETUP_TAB_LABELS.archives })).toBeNull()
  })

  it('顶栏展示流水线/设定分组，以及对话/主笔/故事沙盒/服务/统计五个扁平项', () => {
    renderHeader('/novel/n1/author')
    expect(screen.getByRole('button', { name: '流水线' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '设定' })).toBeTruthy()
    expect(screen.getByRole('button', { name: VIEW_LABELS.chat })).toBeTruthy()
    expect(screen.getByRole('button', { name: VIEW_LABELS.author })).toBeTruthy()
    expect(screen.getByRole('button', { name: VIEW_LABELS.sandbox })).toBeTruthy()
    expect(screen.getByRole('button', { name: VIEW_LABELS.services })).toBeTruthy()
    expect(screen.getByRole('button', { name: VIEW_LABELS.stats })).toBeTruthy()
  })

  it('点开流水线分组展示 workflow 图三个 tab：对话/主笔/故事沙盒', async () => {
    renderHeader('/novel/n1/author')
    await userEvent.click(screen.getByRole('button', { name: '流水线' }))
    expect(await screen.findByRole('menuitem', { name: WORKFLOW_TAB_LABELS.skeleton })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: WORKFLOW_TAB_LABELS.runtime })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: WORKFLOW_TAB_LABELS.sandbox })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '编排配置' })).toBeNull()
  })

  it('运行页有未读时在对应扁平按钮显示红点', () => {
    renderHeader('/novel/n1/author', { ...EMPTY_VIEW_UNREAD, chat: true })
    expect(screen.getByRole('button', { name: VIEW_LABELS.chat }).querySelector('.bg-red-500')).toBeTruthy()
  })

  it('点开设定分组展示世界观/人物/故事/角色档案四项', async () => {
    renderHeader('/novel/n1/setup/world')
    await userEvent.click(screen.getByRole('button', { name: '设定' }))
    expect(await screen.findByRole('menuitem', { name: SETUP_TAB_LABELS.world })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: SETUP_TAB_LABELS.cast })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: SETUP_TAB_LABELS.plot })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: SETUP_TAB_LABELS.archives })).toBeTruthy()
  })

  it('子项有未读时，父级分组触发项聚合显示红点', () => {
    renderHeader('/novel/n1/setup/world', { ...EMPTY_VIEW_UNREAD, archives: true })
    const setupTrigger = screen.getByRole('button', { name: '设定' })
    expect(setupTrigger.querySelector('.bg-red-500')).toBeTruthy()
  })

  it('正在查看的子页即使未读也不在父级冒红点', () => {
    renderHeader('/novel/n1/setup/archives', { ...EMPTY_VIEW_UNREAD, archives: true })
    const setupTrigger = screen.getByRole('button', { name: '设定' })
    expect(setupTrigger.querySelector('.bg-red-500')).toBeNull()
  })
})
