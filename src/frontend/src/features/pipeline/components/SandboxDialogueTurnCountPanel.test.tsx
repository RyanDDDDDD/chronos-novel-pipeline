import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SandboxDialogueTurnCountPanel from '@/features/pipeline/components/SandboxDialogueTurnCountPanel'
import { renderWithClient } from '@/test/renderWithClient'
import { SidebarProvider } from '@/shared/components/ui/sidebar'

vi.mock('@/shared/utils/novels', () => ({
  getSandboxDialogueTurnCount: vi.fn(),
  setSandboxDialogueTurnCount: vi.fn(),
}))
import { getSandboxDialogueTurnCount, setSandboxDialogueTurnCount } from '@/shared/utils/novels'

const toastErrorMock = vi.fn()
vi.mock('@/shared/hooks/useToast', () => ({
  useToast: () => ({ error: toastErrorMock, success: vi.fn() }),
}))

let mockStoredValue: number | null = null

beforeEach(() => {
  cleanup()
  mockStoredValue = null
  toastErrorMock.mockReset()
  vi.mocked(getSandboxDialogueTurnCount).mockReset().mockImplementation(async () => mockStoredValue)
  vi.mocked(setSandboxDialogueTurnCount).mockReset().mockImplementation(async (_novelId, value) => {
    mockStoredValue = value
    return { ok: true }
  })
})
afterEach(() => cleanup())

function renderPanel() {
  renderWithClient(
    <SidebarProvider>
      <SandboxDialogueTurnCountPanel novelId="default" />
    </SidebarProvider>,
  )
}

describe('SandboxDialogueTurnCountPanel', () => {
  it('未配置时显示自动 placeholder，输入框为空', async () => {
    renderPanel()
    const input = await screen.findByLabelText('台词草稿目标行数') as HTMLInputElement
    expect(input.value).toBe('')
    expect(input.placeholder).toBe('自动')
  })

  it('已配置时回显该整数', async () => {
    mockStoredValue = 7
    renderPanel()
    const input = await screen.findByLabelText('台词草稿目标行数') as HTMLInputElement
    await waitFor(() => expect(input.value).toBe('7'))
  })

  it('输入数字后失焦触发保存', async () => {
    renderPanel()
    const input = await screen.findByLabelText('台词草稿目标行数') as HTMLInputElement
    fireEvent.change(input, { target: { value: '9' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(setSandboxDialogueTurnCount).toHaveBeenCalledWith('default', 9)
    })
  })

  it('超过 20 会被 clamp 到 20 再保存', async () => {
    renderPanel()
    const input = await screen.findByLabelText('台词草稿目标行数') as HTMLInputElement
    fireEvent.change(input, { target: { value: '99' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(setSandboxDialogueTurnCount).toHaveBeenCalledWith('default', 20)
    })
    expect(input.value).toBe('20')
  })

  it('清空输入后失焦提交 null（恢复自动）', async () => {
    mockStoredValue = 7
    renderPanel()
    const input = await screen.findByLabelText('台词草稿目标行数') as HTMLInputElement
    await waitFor(() => expect(input.value).toBe('7'))
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(setSandboxDialogueTurnCount).toHaveBeenCalledWith('default', null)
    })
  })

  it('按 Enter 也会提交', async () => {
    renderPanel()
    const input = await screen.findByLabelText('台词草稿目标行数') as HTMLInputElement
    input.focus()
    fireEvent.change(input, { target: { value: '4' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => {
      expect(setSandboxDialogueTurnCount).toHaveBeenCalledWith('default', 4)
    })
  })

  it('保存返回 ok:false 时提示错误而不是静默吞掉', async () => {
    vi.mocked(setSandboxDialogueTurnCount).mockReset().mockResolvedValue({ ok: false, error: '写入失败' })
    renderPanel()
    const input = await screen.findByLabelText('台词草稿目标行数') as HTMLInputElement
    fireEvent.change(input, { target: { value: '9' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalledWith('写入失败')
    })
  })

  it('Skill tab 显示空态提示', async () => {
    renderPanel()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Skill' }))
    expect(await screen.findByText('暂无可配置 Skill')).toBeTruthy()
  })
})
