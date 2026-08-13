import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '@testing-library/react'
import PipelineSidePanel from '@/features/pipeline/components/PipelineSidePanel'
import { SidebarProvider } from '@/shared/components/ui/sidebar'

afterEach(() => cleanup())

function renderPanel(skillContent?: React.ReactNode) {
  return render(
    <SidebarProvider defaultOpen>
      <PipelineSidePanel title="测试面板" hint="测试hint" skillContent={skillContent}>
        <div>参数内容</div>
      </PipelineSidePanel>
    </SidebarProvider>,
  )
}

describe('PipelineSidePanel', () => {
  it('不传 skillContent 时单页渲染，无 tab 切换', () => {
    renderPanel()
    expect(screen.getByText('参数内容')).toBeTruthy()
    expect(screen.queryByRole('tab')).toBeNull()
  })

  it('传入 skillContent 时渲染两个 tab，默认显示参数页', () => {
    renderPanel(<div>Skill内容</div>)
    expect(screen.getByRole('tab', { name: '参数' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Skill' })).toBeTruthy()
    expect(screen.getByText('参数内容')).toBeTruthy()
    expect(screen.queryByText('Skill内容')).toBeNull()
  })

  it('点击 Skill tab 切到 Skill 页', async () => {
    renderPanel(<div>Skill内容</div>)
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Skill' }))
    expect(screen.getByText('Skill内容')).toBeTruthy()
  })
})
