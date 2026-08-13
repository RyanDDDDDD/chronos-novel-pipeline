import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import ProseStylePanel from '@/features/setup/components/ProseStylePanel'
import { renderWithClient } from '@/test/renderWithClient'

vi.mock('@/shared/utils/novels', () => ({
  listProseStyles: vi.fn(),
  getProseStyle: vi.fn(),
  setProseStyle: vi.fn(),
  getProseStylePresetContent: vi.fn(),
}))
import { listProseStyles, getProseStyle, setProseStyle, getProseStylePresetContent } from '@/shared/utils/novels'

beforeEach(() => {
  cleanup()
  vi.mocked(listProseStyles).mockResolvedValue([
    { id: 'plain-direct', title: '语感调色：大白话直白体' },
    { id: 'cinematic', title: '镜头感' },
  ])
  vi.mocked(getProseStyle).mockResolvedValue({ preset: 'cinematic', custom_addendum: '镜头' })
  vi.mocked(setProseStyle).mockResolvedValue({ ok: true })
  vi.mocked(getProseStylePresetContent).mockResolvedValue({ id: 'cinematic', content: '# 语感调色：电影运镜' })
})

describe('ProseStylePanel', () => {
  it('加载服务端文风并渲染 preset 选项', async () => {
    renderWithClient(<ProseStylePanel novelId="default" onClose={() => {}} />)
    expect(await screen.findByText('镜头感')).toBeTruthy()
    expect(screen.getByRole('combobox').textContent).toContain('镜头感')
  })

  it('保存调用 setProseStyle 并关闭', async () => {
    const onClose = vi.fn()
    renderWithClient(<ProseStylePanel novelId="default" onClose={onClose} />)
    await screen.findByText('镜头感')
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(setProseStyle).toHaveBeenCalledWith('default', expect.objectContaining({ preset: 'cinematic' })))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('未传 onClose 时不渲染取消按钮，仍可保存', async () => {
    renderWithClient(<ProseStylePanel novelId="default" />)
    await screen.findByText('镜头感')
    expect(screen.queryByText('取消')).toBeNull()
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(setProseStyle).toHaveBeenCalled())
  })

  it('点击预览按钮展示当前选中 preset 的正文', async () => {
    renderWithClient(<ProseStylePanel novelId="default" onClose={() => {}} />)
    await screen.findByText('镜头感')
    fireEvent.click(screen.getByTitle('预览文风内容'))
    expect(await screen.findByText('文风预览')).toBeTruthy()
    await waitFor(() => expect(getProseStylePresetContent).toHaveBeenCalledWith('cinematic'))
    expect(await screen.findByText('语感调色：电影运镜')).toBeTruthy()
  })

  it('已有自定义追加内容时默认渲染为只读 Markdown，点击后切回可编辑 textarea', async () => {
    vi.mocked(getProseStyle).mockResolvedValue({ preset: 'cinematic', custom_addendum: '**加重** 语气' })
    renderWithClient(<ProseStylePanel novelId="default" onClose={() => {}} />)
    await screen.findByText('镜头感')

    expect(screen.queryByPlaceholderText(/本书额外文风要求/)).toBeNull()
    const view = await screen.findByTitle('点击编辑')
    expect(view.textContent).toContain('加重')

    fireEvent.click(view)
    const textarea = await screen.findByPlaceholderText(/本书额外文风要求/)
    expect((textarea as HTMLTextAreaElement).value).toBe('**加重** 语气')
  })
})
