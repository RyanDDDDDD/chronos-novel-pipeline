import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { Provider } from 'react-redux'
import { buildTestStore } from '@/test/renderWithClient'
import ServiceStatusIcons from '@/shared/components/ServiceStatusIcons'
import type { RootState } from '@/shared/store/store'

afterEach(() => cleanup())

function renderIcons(preloadedState: Partial<RootState>, collapsed = false) {
  const store = buildTestStore(preloadedState)
  return render(
    <Provider store={store}><ServiceStatusIcons collapsed={collapsed} /></Provider>,
  )
}

describe('ServiceStatusIcons', () => {
  it('renders ok status with emerald dot', () => {
    renderIcons({
      servicePing: {
        llm: { status: 'ok', error: null },
        search: { status: 'unknown', error: null },
      },
    })
    expect(screen.getByTitle('LLM已连接').className).toContain('bg-emerald-500')
  })

  it('renders error status with tooltip containing error message', () => {
    renderIcons({
      servicePing: {
        llm: { status: 'unknown', error: null },
        search: { status: 'error', error: '401 Unauthorized' },
      },
    })
    expect(screen.getByTitle('检索连接失败：401 Unauthorized').className).toContain('bg-red-500')
  })

  it('renders disabled status distinctly from unknown', () => {
    renderIcons({
      servicePing: {
        llm: { status: 'unknown', error: null },
        search: { status: 'disabled', error: null },
      },
    })
    expect(screen.getByTitle(/启动自动检测已关闭/)).toBeTruthy()
  })

  it('collapsed prop stacks the dots vertically without labels', () => {
    renderIcons({
      servicePing: {
        llm: { status: 'unknown', error: null },
        search: { status: 'unknown', error: null },
      },
    }, true)
    expect(screen.queryByText('LLM')).toBeNull()
  })
})
